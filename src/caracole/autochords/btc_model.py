# Copyright (c) 2019 Jonggwon Park. MIT License: see LICENSE-BTC in this directory.
"""The BTC network, vendored for inference.

BTC is the Bi-directional Transformer for Chord recognition (Jonggwon Park et
al., "A Bi-Directional Transformer for Musical Chord Recognition", ISMIR 2019).
This is the model from ``btc_model.py`` and ``utils/transformer_modules.py`` of
https://github.com/jayg996/BTC-ISMIR19 at commit
2682317be668032e6e4b269ded36adaa2ad57df0, trimmed to what inference needs:

- the dropout layers, the training loss, the attention-map plumbing and the
  output layer's unused LSTM are gone; none of them affects a prediction;
- the masks and the timing signal are non-persistent buffers, so they follow
  ``.to(device)`` and stay out of the state dict;
- ``np.float``, which NumPy removed, is ``float``.

Module and attribute names are unchanged, so the published state dicts load
with ``strict=True`` once the LSTM's keys are dropped. The arithmetic is
unchanged too, including two quirks the published weights were trained with:
the layer norm divides by the unbiased standard deviation plus epsilon, and the
position-wise feed-forward block applies ReLU after its last layer as well.
"""

from __future__ import annotations

import math

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn


def _bias_mask(max_length: int) -> torch.Tensor:
    """-inf above the diagonal, so position i attends only to positions up to i."""
    mask = np.triu(np.full([max_length, max_length], -np.inf), 1)
    return torch.from_numpy(mask).type(torch.FloatTensor).unsqueeze(0).unsqueeze(1)


def _timing_signal(
    length: int, channels: int, min_timescale: float = 1.0, max_timescale: float = 1.0e4
) -> torch.Tensor:
    """The sinusoidal position signal of tensor2tensor, shaped [1, length, channels]."""
    position = np.arange(length)
    num_timescales = channels // 2
    log_timescale_increment = math.log(float(max_timescale) / float(min_timescale)) / (
        float(num_timescales) - 1
    )
    inv_timescales = min_timescale * np.exp(
        np.arange(num_timescales).astype(float) * -log_timescale_increment
    )
    scaled_time = np.expand_dims(position, 1) * np.expand_dims(inv_timescales, 0)
    signal = np.concatenate([np.sin(scaled_time), np.cos(scaled_time)], axis=1)
    signal = np.pad(signal, [[0, 0], [0, channels % 2]], "constant", constant_values=[0.0, 0.0])
    return torch.from_numpy(signal.reshape([1, length, channels])).type(torch.FloatTensor)


class LayerNorm(nn.Module):
    def __init__(self, features: int, eps: float = 1e-6):
        super().__init__()
        self.gamma = nn.Parameter(torch.ones(features))
        self.beta = nn.Parameter(torch.zeros(features))
        self.eps = eps

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        mean = x.mean(-1, keepdim=True)
        std = x.std(-1, keepdim=True)
        return self.gamma * (x - mean) / (std + self.eps) + self.beta


class MultiHeadAttention(nn.Module):
    def __init__(
        self,
        input_depth: int,
        total_key_depth: int,
        total_value_depth: int,
        output_depth: int,
        num_heads: int,
        bias_mask: torch.Tensor | None = None,
    ):
        super().__init__()
        if total_key_depth % num_heads or total_value_depth % num_heads:
            raise ValueError("key and value depths must be divisible by the number of heads")
        self.num_heads = num_heads
        self.query_scale = (total_key_depth // num_heads) ** -0.5
        self.register_buffer("bias_mask", bias_mask, persistent=False)
        self.query_linear = nn.Linear(input_depth, total_key_depth, bias=False)
        self.key_linear = nn.Linear(input_depth, total_key_depth, bias=False)
        self.value_linear = nn.Linear(input_depth, total_value_depth, bias=False)
        self.output_linear = nn.Linear(total_value_depth, output_depth, bias=False)

    def _split_heads(self, x: torch.Tensor) -> torch.Tensor:
        batch, length, depth = x.shape
        return x.view(batch, length, self.num_heads, depth // self.num_heads).permute(0, 2, 1, 3)

    def _merge_heads(self, x: torch.Tensor) -> torch.Tensor:
        batch, heads, length, depth = x.shape
        return x.permute(0, 2, 1, 3).contiguous().view(batch, length, depth * heads)

    def forward(
        self, queries: torch.Tensor, keys: torch.Tensor, values: torch.Tensor
    ) -> torch.Tensor:
        queries = self._split_heads(self.query_linear(queries)) * self.query_scale
        keys = self._split_heads(self.key_linear(keys))
        values = self._split_heads(self.value_linear(values))
        logits = torch.matmul(queries, keys.permute(0, 1, 3, 2))
        if self.bias_mask is not None:
            logits = logits + self.bias_mask[:, :, : logits.shape[-2], : logits.shape[-1]].type_as(
                logits
            )
        weights = F.softmax(logits, dim=-1)
        return self.output_linear(self._merge_heads(torch.matmul(weights, values)))


class Conv(nn.Module):
    """A 1-D convolution over [batch, length, channels], padded on both sides."""

    def __init__(self, input_size: int, output_size: int, kernel_size: int):
        super().__init__()
        self.pad = nn.ConstantPad1d((kernel_size // 2, (kernel_size - 1) // 2), 0)
        self.conv = nn.Conv1d(input_size, output_size, kernel_size=kernel_size, padding=0)

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        return self.conv(self.pad(inputs.permute(0, 2, 1))).permute(0, 2, 1)


class PositionwiseFeedForward(nn.Module):
    """Two convolutions of width 3, each followed by ReLU (upstream's layer_config "cc")."""

    def __init__(self, input_depth: int, filter_size: int, output_depth: int):
        super().__init__()
        self.layers = nn.ModuleList(
            [
                Conv(input_depth, filter_size, kernel_size=3),
                Conv(filter_size, output_depth, kernel_size=3),
            ]
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        for layer in self.layers:
            x = torch.relu(layer(x))
        return x


class SelfAttentionBlock(nn.Module):
    def __init__(
        self,
        hidden_size: int,
        total_key_depth: int,
        total_value_depth: int,
        filter_size: int,
        num_heads: int,
        bias_mask: torch.Tensor,
    ):
        super().__init__()
        self.multi_head_attention = MultiHeadAttention(
            hidden_size, total_key_depth, total_value_depth, hidden_size, num_heads, bias_mask
        )
        self.positionwise_convolution = PositionwiseFeedForward(
            hidden_size, filter_size, hidden_size
        )
        self.layer_norm_mha = LayerNorm(hidden_size)
        self.layer_norm_ffn = LayerNorm(hidden_size)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x_norm = self.layer_norm_mha(x)
        x = x + self.multi_head_attention(x_norm, x_norm, x_norm)
        return x + self.positionwise_convolution(self.layer_norm_ffn(x))


class BiDirectionalSelfAttention(nn.Module):
    """A forward (past-only) and a backward (future-only) block, joined by a linear layer."""

    def __init__(
        self,
        hidden_size: int,
        total_key_depth: int,
        total_value_depth: int,
        filter_size: int,
        num_heads: int,
        max_length: int,
    ):
        super().__init__()
        params = (hidden_size, total_key_depth, total_value_depth, filter_size, num_heads)
        self.attn_block = SelfAttentionBlock(*params, _bias_mask(max_length))
        self.backward_attn_block = SelfAttentionBlock(
            *params, torch.transpose(_bias_mask(max_length), dim0=2, dim1=3)
        )
        self.linear = nn.Linear(hidden_size * 2, hidden_size)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.linear(torch.cat((self.attn_block(x), self.backward_attn_block(x)), dim=2))


class BiDirectionalSelfAttentionLayers(nn.Module):
    def __init__(
        self,
        embedding_size: int,
        hidden_size: int,
        num_layers: int,
        num_heads: int,
        total_key_depth: int,
        total_value_depth: int,
        filter_size: int,
        max_length: int,
    ):
        super().__init__()
        self.register_buffer(
            "timing_signal", _timing_signal(max_length, hidden_size), persistent=False
        )
        self.embedding_proj = nn.Linear(embedding_size, hidden_size, bias=False)
        self.self_attn_layers = nn.Sequential(
            *[
                BiDirectionalSelfAttention(
                    hidden_size,
                    total_key_depth,
                    total_value_depth,
                    filter_size,
                    num_heads,
                    max_length,
                )
                for _ in range(num_layers)
            ]
        )
        self.layer_norm = LayerNorm(hidden_size)

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        x = self.embedding_proj(inputs)
        x = x + self.timing_signal[:, : inputs.shape[1], :].type_as(inputs)
        return self.layer_norm(self.self_attn_layers(x))


class SoftmaxOutputLayer(nn.Module):
    def __init__(self, hidden_size: int, output_size: int):
        super().__init__()
        self.output_projection = nn.Linear(hidden_size, output_size)

    def forward(self, hidden: torch.Tensor) -> torch.Tensor:
        return self.output_projection(hidden)


class BTCModel(nn.Module):
    """BTC with the published hyperparameters (``run_config.yaml``).

    ``forward`` takes [batch, timestep, feature_size] normalized log-CQT frames and
    returns [batch, timestep, num_chords] logits; the predicted chord is the argmax.
    """

    def __init__(
        self,
        *,
        num_chords: int = 170,
        feature_size: int = 144,
        timestep: int = 108,
        num_layers: int = 8,
        num_heads: int = 4,
        hidden_size: int = 128,
        total_key_depth: int = 128,
        total_value_depth: int = 128,
        filter_size: int = 128,
    ):
        super().__init__()
        self.timestep = timestep
        self.self_attn_layers = BiDirectionalSelfAttentionLayers(
            feature_size,
            hidden_size,
            num_layers,
            num_heads,
            total_key_depth,
            total_value_depth,
            filter_size,
            timestep,
        )
        self.output_layer = SoftmaxOutputLayer(hidden_size, num_chords)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.output_layer(self.self_attn_layers(x))
