(() => {
  "use strict";
  // Hear a chord: a guitar's voicing strummed in the browser, for the sheet viewer and a songbook (viewer.js
  // calls it; it runs before viewer.js). A plucked-string synthesis (Karplus-Strong: a burst of noise
  // fed back through a delay a period long, softened a little each time round) makes each string's note
  // into an AudioBuffer, played by Web Audio. No sample, no worklet, nothing loaded: the page's policy
  // needs no new source, from a file or in a server's sandbox alike.
  //
  // Never on its own: the AudioContext is made on the first tap that asks for a sound (a user gesture,
  // navigator.userActivation), and a context suspended (by this script once the page is hidden, or after
  // two seconds of silence, so a phone's audio can sleep; by the browser for a phone call) is resumed on
  // the next tap, never before. Hidden, the page falls silent at once. One sound at a time: a strum, or a
  // progression's next chord, stops the one before it.
  //
  // window.caracoleSound:
  //   notes(position, capo)        the MIDI notes a position sounds, low string first: a position as the
  //                                viewer's data has one ([frets, fingers, base fret, barres]: voicings.py),
  //                                in standard tuning (E2 A2 D3 G3 B3 E4), the capo on fret ``capo``
  //   frequencies(position, capo)  the same in Hz
  //   strum(position, {capo})      strums it now, low to high; false when nothing sounds (no tap asked,
  //                                no Web Audio, the volume off, a position with no string played)
  //   play(chords, {bpm, beats, every, onChord, onEnd})
  //                                plays a progression, a chord a bar: ``chords`` lists
  //                                {position, capo} (null, or a position null, for a bar of silence: a
  //                                chord with no shape, N.C.); ``bpm`` the tempo (80), ``beats`` a bar
  //                                (4), a strum every ``every`` beats (1, the bar's first the strongest);
  //                                ``onChord(i)`` as chord i's bar begins, ``onEnd(done)`` once, when it
  //                                ran to the end (true) or was stopped (false). It returns
  //                                {playing, stop()}; ``playing`` is false when it couldn't start (as
  //                                strum's false) or has ended. Call it from a tap, as strum.
  //   stop()                       stops whatever plays
  //   setVolume(v)                 0 (off) to 1; held for the next sounds, and the one playing
  //   pluck(hz, rate, seconds)     one plucked note's samples (a Float32Array), as a buffer holds them
  //   available                    whether this browser has Web Audio
  //
  // The frequencies strummed last are on <html data-heard> ("130.81 164.81 …"), for the tests.
  const TUNING = [40, 45, 50, 55, 59, 64];  // E2 A2 D3 G3 B3 E4, MIDI (voicings.TUNING)
  const RING = 2.6;  // seconds a note's buffer lasts
  const GAP = 0.022;  // seconds from one string to the next in a strum
  const DAMP = 0.035;  // the time constant a sound stopped (or the next one) fades with
  const IDLE = 2;  // seconds of silence before the context is suspended
  const LEVEL = 0.32;  // each string's level, at full volume
  // The string's loss: each sample is this much of the one a period and a sample back, the rest of the one a
  // period back. 0.5 (Karplus and Strong's average) dulls a note within half a second; less rings brighter.
  const BLEND = 0.3;
  const Context = window.AudioContext || window.webkitAudioContext || null;
  const doc = document.documentElement;
  let context = null, out = null, volume = 0.6;

  const notes = (position, capo) => {
    if (!Array.isArray(position)) return [];
    const frets = String(position[0] || "");
    const base = Math.max(1, Math.round(Number(position[2]) || 1));
    const up = Math.max(0, Math.round(Number(capo) || 0));
    if (frets.length !== TUNING.length) return [];
    const found = [];
    for (let s = 0; s < TUNING.length; s++) {
      if (!/^[0-9]$/.test(frets[s])) continue;  // "x": muted
      const n = Number(frets[s]);
      found.push(TUNING[s] + up + (n ? n + base - 1 : 0));
    }
    return found;
  };
  const hz = (midi) => 440 * Math.pow(2, (midi - 69) / 12);
  const frequencies = (position, capo) => notes(position, capo).map(hz);

  // One plucked string: noise, softened (a one-pole low pass) and with no DC, fills the first period;
  // each sample after is a blend of two a period back (BLEND: the string's loss, more for higher
  // harmonics) times ``loss`` (its ring: lower notes ring longer), through an all-pass that tunes the
  // loop's delay to the period's fraction of a sample. The last 150 ms fade out, the first 2 ms in.
  const pluck = (frequency, rate, seconds) => {
    const length = Math.max(1, Math.round(rate * seconds));
    const s = new Float32Array(length);
    const period = rate / frequency;
    const size = Math.max(2, Math.floor(period - BLEND - 0.1));  // the delay's whole samples; the rest is the all-pass's
    const fraction = period - BLEND - size;  // 0.1 to 1.1: the blend delays BLEND of a sample
    const c = (1 - fraction) / (1 + fraction);
    const ring = Math.min(6, Math.max(1.5, 6 * Math.pow(82.4 / frequency, 0.5)));  // seconds to fall 60 dB
    const loss = Math.pow(0.001, 1 / (frequency * ring));
    let low = 0, mean = 0;
    const first = Math.min(size, length);
    for (let i = 0; i < first; i++) {
      low += 0.55 * (Math.random() * 2 - 1 - low);
      s[i] = low;
      mean += low;
    }
    mean /= first;
    let top = 0;
    for (let i = 0; i < first; i++) top = Math.max(top, Math.abs((s[i] -= mean)));
    if (top > 0) for (let i = 0; i < first; i++) s[i] /= top;
    let before = 0;  // the average a sample back, into the all-pass
    for (let i = first; i < length; i++) {
      const v = loss * ((1 - BLEND) * s[i - size] + BLEND * (i - size - 1 >= 0 ? s[i - size - 1] : 0));
      s[i] = c * v + before - c * s[i - 1];
      before = v;
    }
    const fadeIn = Math.min(length, Math.round(rate * 0.002));
    for (let i = 0; i < fadeIn; i++) s[i] *= i / fadeIn;
    const fadeOut = Math.min(length, Math.round(rate * 0.15));
    for (let i = 0; i < fadeOut; i++) s[length - 1 - i] *= i / fadeOut;
    return s;
  };

  // A note's buffer, kept for the next strum of it (a progression strums the same notes again and again).
  const buffers = new Map();
  const bufferOf = (midi) => {
    const key = context.sampleRate + ":" + midi;
    let buffer = buffers.get(key);
    if (!buffer) {
      buffer = context.createBuffer(1, Math.round(context.sampleRate * RING), context.sampleRate);
      buffer.getChannelData(0).set(pluck(hz(midi), context.sampleRate, RING));
      if (buffers.size >= 32) buffers.delete(buffers.keys().next().value);
      buffers.set(key, buffer);
    }
    return buffer;
  };

  // Asked for by a tap (or a browser that can't tell, which has no userActivation).
  const tapped = () => !navigator.userActivation || navigator.userActivation.isActive;
  // The context, made on a tap; one not running is resumed, only on a tap. null when nothing may sound.
  const ready = () => {
    if (!Context || volume <= 0) return null;
    clearTimeout(idle);
    if (!context) {
      if (!tapped() || document.visibilityState === "hidden") return null;
      try {
        context = new Context({ latencyHint: "interactive" });
      } catch (err) {
        return null;
      }
      out = context.createGain();
      out.gain.value = volume;
      const tone = context.createBiquadFilter();  // a little of a guitar's body: the top rounded off
      tone.type = "lowpass";
      tone.frequency.value = 5200;
      tone.Q.value = 0.5;
      out.connect(tone);
      tone.connect(context.destination);
    }
    if (context.state !== "running") {
      if (!tapped() || document.visibilityState === "hidden") return null;
      try {
        context.resume().catch(() => {});
      } catch (err) { /* it stays as it is */ }
    }
    return context;
  };
  // Once the context runs (at once, or once a resume asked for has done), unless the page was hidden since.
  const whenRunning = (go) => {
    if (context.state === "running") go();
    else context.resume().then(() => { if (document.visibilityState !== "hidden") go(); }, () => {});
  };

  let progression = null;  // the progression playing: {playing, stop}
  // The sounds still playing, each its gain and its sources: the last one, and those fading under it.
  // ``at``: a time on the context's clock.
  // Once nothing has played for IDLE seconds, the context is suspended, so the device's audio can sleep;
  // the next tap resumes it (ready).
  const live = new Set();
  let idle = 0;
  const rest = () => {
    clearTimeout(idle);
    if (live.size || progression) return;
    idle = setTimeout(() => {
      if (!live.size && !progression && context.state === "running") context.suspend().catch(() => {});
    }, IDLE * 1000);
  };
  // Damped from ``at`` (at once, ``hard``: the page went out of sight, where nothing may sound on).
  const damp = (which, at, hard) => {
    const when = Math.max(at, context.currentTime);
    which.gain.gain.cancelScheduledValues(when);
    if (hard) which.gain.gain.setValueAtTime(0, when);
    else which.gain.gain.setTargetAtTime(0, when, DAMP);
    for (const source of which.sources) {
      try {
        source.stop(hard ? when : when + DAMP * 8);
      } catch (err) { /* stopped already */ }
    }
  };
  const silence = (at, hard) => {
    for (const which of live) damp(which, at, hard);
  };
  // A strum at ``at``, low string first (``up``: high first), the sounds before it stopped as it begins.
  const sound = (midis, at, level, up) => {
    silence(at);
    const gain = context.createGain();
    gain.gain.value = level;
    gain.connect(out);
    const order = up ? midis.slice().reverse() : midis;
    const which = { gain, sources: [] };
    let left = order.length;
    which.sources = order.map((midi, n) => {
      const source = context.createBufferSource();
      source.buffer = bufferOf(midi);
      source.connect(gain);
      source.onended = () => {
        if (--left === 0) {
          live.delete(which);
          gain.disconnect();
          rest();
        }
      };
      source.start(at + n * GAP);
      return source;
    });
    live.add(which);
    clearTimeout(idle);
    doc.dataset.heard = midis.map((midi) => hz(midi).toFixed(2)).join(" ");
  };

  const stop = (hard) => {
    if (progression) progression.stop();
    if (context) silence(context.currentTime, hard);
  };

  const strum = (position, options) => {
    const midis = notes(position, options && options.capo);
    if (!midis.length || !ready()) return false;
    if (progression) progression.stop();
    whenRunning(() => sound(midis, context.currentTime + 0.005, LEVEL, false));
    return true;
  };

  const play = (chords, options) => {
    const o = options || {};
    const list = Array.isArray(chords) ? chords : [];
    const bpm = Math.min(600, Math.max(20, Number(o.bpm) || 80));
    const beats = Math.max(1, Math.round(Number(o.beats) || 4));
    const every = Math.max(1, Math.round(Number(o.every) || 1));
    const handle = { playing: false, stop: () => {} };
    if (!list.length || !ready()) return handle;
    stop();
    const beat = 60 / bpm;
    const timers = [];
    let start = 0, next = 0, ticking = 0, over = false;
    // Every strum: [time from the start, chord, beat of its bar]; a bar's first is down and the strongest,
    // and the others alternate up and down.
    const strums = [];
    list.forEach((chord, i) => {
      for (let b = 0; b < beats; b += every) strums.push([(i * beats + b) * beat, i, b]);
    });
    const end = (done) => {
      if (over) return;
      over = true;
      handle.playing = false;
      clearTimeout(ticking);
      for (const timer of timers) clearTimeout(timer);
      if (progression === handle) progression = null;
      if (!done) silence(context.currentTime);
      rest();
      if (typeof o.onEnd === "function") o.onEnd(done);
    };
    // Scheduled a little ahead on the context's clock, as timers in a page are late at times.
    const tick = () => {
      if (over) return;
      const now = context.currentTime;
      while (next < strums.length && start + strums[next][0] < now + 0.3) {
        const [from, i, b] = strums[next];
        const at = start + from;
        const chord = list[i];
        const midis = chord ? notes(chord.position, chord.capo) : [];
        if (b === 0) {
          if (midis.length) sound(midis, at, LEVEL, false);
          else silence(at);  // a bar of silence
          timers.push(setTimeout(() => { if (!over && typeof o.onChord === "function") o.onChord(i); },
            Math.max(0, (at - now) * 1000)));
        } else if (midis.length) sound(midis, at, LEVEL * 0.62, (b / every) % 2 === 1);
        next += 1;
      }
      if (next >= strums.length) {
        timers.push(setTimeout(() => end(true), Math.max(0, (start + list.length * beats * beat - now) * 1000)));
        return;
      }
      ticking = setTimeout(tick, 100);
    };
    handle.playing = true;
    handle.stop = () => end(false);
    progression = handle;
    whenRunning(() => {
      if (over) return;
      start = context.currentTime + 0.05;
      tick();
    });
    return handle;
  };

  const setVolume = (v) => {
    volume = Math.min(1, Math.max(0, Number(v) || 0));
    if (volume <= 0) stop();
    if (out) out.gain.setTargetAtTime(volume, context.currentTime, 0.02);
  };

  // Hidden (another tab, the phone locked) or left, it falls silent at once and lets the device's audio
  // sleep; it plays again on the next tap, which resumes it.
  const hush = () => {
    stop(true);
    if (context && context.state === "running") context.suspend().catch(() => {});
  };
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") hush();
  });
  window.addEventListener("pagehide", hush);

  window.caracoleSound = Object.freeze({
    notes, frequencies, strum, play, stop, setVolume, pluck, available: Boolean(Context),
  });
})();
