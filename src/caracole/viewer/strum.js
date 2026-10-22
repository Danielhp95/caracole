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
  // A progression is scheduled on the context's clock, a little ahead (AHEAD), by a timer that looks every
  // TICK ms; each bar is marked (onChord) and the end told (onEnd) on that clock too. A strum the timer comes
  // to too late (the page was busy) moves the rest of the progression on with it, a beat after the one
  // before: never two chords crammed together, never one out of its order. Stopped (stop(), its handle's,
  // another strum or progression, the volume off, the page hidden or left), nothing scheduled sounds: a
  // note not begun never begins, one ringing fades out (at once where the page is hidden), and no timer of
  // it is left, though the notes cut tell they ended late. A sound still waiting for the context to resume
  // plays only if nothing was asked after it; a context woken for nothing goes back to sleep.
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
  //                                {playing, stop(), tempo(bpm)}; ``playing`` is false when it couldn't
  //                                start (as strum's false) or has ended; ``tempo`` sets the tempo from
  //                                the next strum not yet scheduled on. Call it from a tap, as strum.
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
  const FADE = DAMP * 8;  // seconds a sound stopped takes to fall silent, when its notes stop
  const AHEAD = 0.3;  // seconds of a progression scheduled ahead on the context's clock
  const LEAD = 0.05;  // the least a progression's strum is scheduled ahead: its first, and one that would be late
  const TICK = 50;  // ms between two looks at the clock while a progression plays
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
    idle = 0;
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
    if (context.state !== "running" || asleep) {
      if (!tapped() || document.visibilityState === "hidden") return null;
      asleep = false;
      try {
        context.resume().catch(() => {});
      } catch (err) { /* it stays as it is */ }
    }
    return context;
  };
  // What was asked last: each strum, progression and stop counts one, and a sound waiting for the context
  // to resume plays only if nothing was asked after it.
  let turn = 0;
  // Once the context runs (at once, or once a resume asked for has done), unless the page was hidden or
  // something else was asked since: then, awake for nothing, it goes back to sleep (at once out of sight).
  const whenRunning = (go) => {
    const mine = turn;
    if (context.state === "running") go();
    else {
      context.resume().then(() => {
        if (mine === turn && document.visibilityState !== "hidden") go();
        else if (document.visibilityState === "hidden") sleep();
        else rest();
      }, () => {});
    }
  };

  let progression = null;  // the progression playing: {playing, stop, tempo}
  // The sounds scheduled or still playing: the last one, and those fading under it. Each its gain, its
  // sources and the time each begins (``times``), ``at``, the time it begins, and ``ends``, the time it is
  // silent by (Infinity: it rings out), on the context's clock.
  // Once nothing has played for IDLE seconds, the context is suspended, so the device's audio can sleep;
  // the next tap resumes it (ready). The timer is set only while the context runs and isn't put to sleep
  // already (``asleep``, until a tap resumes it; a browser may tell the state late): the notes cut as the
  // page was hidden may tell they ended after it was.
  const live = new Set();
  let idle = 0, asleep = false;
  const sleep = () => {
    clearTimeout(idle);
    idle = 0;
    if (context && context.state === "running") {
      asleep = true;
      context.suspend().catch(() => {});
    }
  };
  const rest = () => {
    clearTimeout(idle);
    idle = 0;
    if (!context || asleep || context.state !== "running" || live.size || progression) return;
    idle = setTimeout(() => {
      idle = 0;
      if (!live.size && !progression) sleep();
    }, IDLE * 1000);
  };
  // Silent at once: its level to nothing and its notes stopped, so one not begun never begins.
  const cut = (which) => {
    live.delete(which);
    which.ends = 0;
    try {
      which.gain.gain.cancelScheduledValues(0);
      which.gain.gain.value = 0;
    } catch (err) { /* the context is gone */ }
    for (const source of which.sources) {
      try {
        source.stop();
      } catch (err) { /* stopped already */ }
    }
  };
  // Faded out from ``at``, its notes stopped FADE after, and a string it hadn't come to by then never
  // sounds: never later than it was to stop already, so a sound faded by the next strum stays faded under
  // the ones after it.
  const damp = (which, at) => {
    const when = Math.max(at, context.currentTime);
    if (which.ends <= when + FADE) return;
    which.ends = when + FADE;
    which.gain.gain.cancelScheduledValues(when);
    which.gain.gain.setTargetAtTime(0, when, DAMP);
    which.sources.forEach((source, n) => {
      try {
        source.stop(which.times[n] >= when ? when : which.ends);
      } catch (err) { /* stopped already */ }
    });
  };
  // Every sound from ``at`` on (now, at the soonest): one that hasn't begun by then never does, the others
  // fade out; all cut at once (``hard``) where nothing may sound on: the page went out of sight.
  const silence = (at, hard) => {
    const from = Math.max(at, context.currentTime);
    for (const which of Array.from(live)) {
      if (hard || which.at >= from) cut(which);
      else damp(which, from);
    }
  };
  // A strum at ``at``, low string first (``up``: high first), the sounds before it stopped as it begins.
  const sound = (midis, at, level, up) => {
    const order = up ? midis.slice().reverse() : midis;
    const made = order.map(bufferOf);
    silence(at);
    const gain = context.createGain();
    gain.gain.value = level;
    gain.connect(out);
    const which = { gain, sources: [], times: made.map((_, n) => at + n * GAP), at, ends: Infinity };
    let left = made.length;
    which.sources = made.map((buffer, n) => {
      const source = context.createBufferSource();
      source.buffer = buffer;
      source.connect(gain);
      source.onended = () => {
        if (--left === 0) {
          live.delete(which);
          gain.disconnect();
          rest();
        }
      };
      source.start(which.times[n]);
      return source;
    });
    live.add(which);
    clearTimeout(idle);
    idle = 0;
    doc.dataset.heard = midis.map((midi) => hz(midi).toFixed(2)).join(" ");
  };

  const stop = (hard) => {
    turn += 1;
    if (progression) progression.stop();
    if (context) {
      silence(context.currentTime, hard);
      rest();
    }
  };

  const strum = (position, options) => {
    const midis = notes(position, options && options.capo);
    if (!midis.length || !ready()) return false;
    stop();
    whenRunning(() => {
      midis.forEach(bufferOf);  // made before the clock is read, so no string starts late
      sound(midis, context.currentTime + 0.005, LEVEL, false);
    });
    return true;
  };

  const tempoOf = (bpm) => Math.min(600, Math.max(20, Number(bpm) || 80));
  const play = (chords, options) => {
    const o = options || {};
    const list = Array.isArray(chords) ? chords : [];
    const beats = Math.max(1, Math.round(Number(o.beats) || 4));
    const every = Math.max(1, Math.round(Number(o.every) || 1));
    const handle = { playing: false, stop: () => {}, tempo: () => {} };
    if (!list.length || !ready()) return handle;
    stop();
    const chordNotes = list.map((chord) => (chord ? notes(chord.position, chord.capo) : []));
    // Every strum: [its beat, from the first, chord, beat of its bar]; a bar's first is down and the
    // strongest, and the others alternate up and down.
    const strums = [];
    list.forEach((chord, i) => {
      for (let b = 0; b < beats; b += every) strums.push([i * beats + b, i, b]);
    });
    // On the context's clock: beat ``from`` at ``origin``, and one every ``beat`` seconds from there.
    let beat = 60 / tempoOf(o.bpm), origin = 0, from = 0;
    const timeOf = (n) => origin + (n - from) * beat;
    const bars = [];  // [time, chord] of each bar scheduled, until it is marked
    let next = 0, ticking = 0, over = false;
    const end = (done) => {
      if (over) return;
      over = true;
      handle.playing = false;
      clearTimeout(ticking);
      ticking = 0;
      if (progression === handle) progression = null;
      if (!done) {
        turn += 1;
        silence(context.currentTime);
      }
      rest();
      if (typeof o.onEnd === "function") o.onEnd(done);
    };
    // Scheduled a little ahead on the context's clock, as timers in a page are late at times.
    const tick = () => {
      ticking = 0;
      if (over) return;
      while (next < strums.length && timeOf(strums[next][0]) < context.currentTime + AHEAD) {
        const [n, i, b] = strums[next];
        const midis = chordNotes[i];
        midis.forEach(bufferOf);  // made before the clock is read: the first time, a note takes a while
        const soonest = context.currentTime + LEAD;
        if (timeOf(n) < soonest) origin += soonest - timeOf(n);  // late: the rest moves on with it
        const at = timeOf(n);
        if (b === 0) {
          if (midis.length) sound(midis, at, LEVEL, false);
          else silence(at);  // a bar of silence
          bars.push([at, i]);
        } else if (midis.length) sound(midis, at, LEVEL * 0.62, (b / every) % 2 === 1);
        next += 1;
      }
      while (bars.length && bars[0][0] <= context.currentTime) {
        const i = bars.shift()[1];
        if (typeof o.onChord === "function") o.onChord(i);
        if (over) return;
      }
      if (next >= strums.length && !bars.length && context.currentTime >= timeOf(list.length * beats)) {
        end(true);
        return;
      }
      ticking = setTimeout(tick, TICK);
    };
    handle.playing = true;
    handle.stop = () => end(false);
    // The strums scheduled keep their times; the next one comes the new beat after the last of them.
    handle.tempo = (bpm) => {
      if (over) return;
      const pivot = next > 0 ? strums[next - 1][0] : 0;
      origin = timeOf(pivot);
      from = pivot;
      beat = 60 / tempoOf(bpm);
    };
    progression = handle;
    whenRunning(() => {
      if (over) return;
      for (const midis of chordNotes) midis.forEach(bufferOf);  // every note made before the first is timed
      origin = context.currentTime + LEAD;
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
    sleep();
  };
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") hush();
  });
  window.addEventListener("pagehide", hush);

  window.caracoleSound = Object.freeze({
    notes, frequencies, strum, play, stop, setVolume, pluck, available: Boolean(Context),
  });
})();
