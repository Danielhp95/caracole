(() => {
  "use strict";
  // Hear a chord: a voicing strummed in the browser, on the guitar, a ukulele or the piano, for the sheet viewer
  // and a songbook (viewer.js calls it; it runs before viewer.js). A plucked-string synthesis (Karplus-Strong: a
  // burst of noise fed back through a delay a period long, softened a little each time round) makes each string's
  // note into an AudioBuffer, and a piano's note is a sum of decaying partials, each a damped resonator, struck
  // together as a block chord (VOICES: each instrument's sound). Web Audio plays them. No sample, no worklet,
  // nothing loaded: the page's policy needs no new source, from a file or in a server's sandbox alike.
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
  //   notes(position, capo, tuning)
  //                                the MIDI notes a position sounds, string by string in its order (a guitar's low
  //                                string first, a ukulele's 4th): a position as the viewer's data has one ([frets,
  //                                fingers, base fret, barres]: voicings.py) on ``tuning`` (each string's open note,
  //                                MIDI, as data.instruments gives it; the guitar's standard tuning, E2 A2 D3 G3 B3
  //                                E4, when none is given), the capo on fret ``capo``; or a piano's ([bass, ...right
  //                                hand], MIDI notes: instruments.py piano_positions), as it is
  //   frequencies(position, capo, tuning)
  //                                the same in Hz
  //   strum(position, {capo, tuning, voice})
  //                                strums it now, string by string (a piano's struck together); ``voice`` the
  //                                instrument's sound, one of ``voices`` (data.instruments' voice: "guitar", the
  //                                default; "ukulele", a shorter, softer ring; "piano"); false when nothing sounds
  //                                (no tap asked, no Web Audio, the volume off, a position with no string played)
  //   play(chords, {bpm, beats, every, onChord, onEnd})
  //                                plays a progression, a chord a bar: ``chords`` lists
  //                                {position, capo, tuning, voice} (null, or a position null, for a bar of silence: a
  //                                chord with no shape, N.C.); ``bpm`` the tempo (80), ``beats`` a bar
  //                                (4), a strum every ``every`` beats (1, the bar's first the strongest);
  //                                ``onChord(i)`` as chord i's bar begins, ``onEnd(done)`` once, when it
  //                                ran to the end (true) or was stopped (false). It returns
  //                                {playing, stop(), tempo(bpm)}; ``playing`` is false when it couldn't
  //                                start (as strum's false) or has ended; ``tempo`` sets the tempo from
  //                                the next strum not yet scheduled on. Call it from a tap, as strum.
  //   stop()                       stops whatever plays
  //   setVolume(v)                 0 (off) to 1; held for the next sounds, and the one playing
  //   pluck(hz, rate, seconds, voice)
  //                                one plucked note's samples (a Float32Array), as a buffer holds them (``voice``:
  //                                "guitar" unless given)
  //   strike(hz, rate, seconds)    one piano note's samples, likewise
  //   voices                       the voices it has, by name
  //   available                    whether this browser has Web Audio
  //
  // The frequencies strummed last are on <html data-heard> ("130.81 164.81 …"), for the tests.
  const TUNING = [40, 45, 50, 55, 59, 64];  // E2 A2 D3 G3 B3 E4, MIDI (voicings.TUNING)
  const RING = 2.6;  // seconds a note's buffer lasts
  const GAP = 0.022;  // seconds from one string to the next in a guitar's strum
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
  // Each instrument's sound: a plucked string ("pluck": its loss, ``blend``, its ring, ``ring`` times the guitar's,
  // its strum's ``gap``) or a struck piano string ("strike": every note at once), each note at ``level``. The
  // ukulele's nylon rings shorter and duller, strummed a little slower.
  const VOICES = Object.freeze({
    guitar: Object.freeze({ kind: "pluck", blend: BLEND, ring: 1, gap: GAP, level: LEVEL }),
    ukulele: Object.freeze({ kind: "pluck", blend: 0.42, ring: 0.45, gap: 0.03, level: LEVEL }),
    piano: Object.freeze({ kind: "strike", gap: 0, level: 0.24 }),
  });
  const voiceOf = (name) => (Object.prototype.hasOwnProperty.call(VOICES, name) ? name : "guitar");
  const Context = window.AudioContext || window.webkitAudioContext || null;
  const doc = document.documentElement;
  let context = null, out = null, volume = 0.6;

  const notes = (position, capo, tuning) => {
    if (!Array.isArray(position)) return [];
    if (typeof position[0] === "number") return position.filter((n) => Number.isInteger(n) && n >= 0 && n < 128);
    const strings = Array.isArray(tuning) && tuning.length && tuning.every((n) => Number.isInteger(n)) ? tuning : TUNING;
    const frets = String(position[0] || "");
    const base = Math.max(1, Math.round(Number(position[2]) || 1));
    const up = Math.max(0, Math.round(Number(capo) || 0));
    if (frets.length !== strings.length) return [];
    const found = [];
    for (let s = 0; s < strings.length; s++) {
      if (!/^[0-9]$/.test(frets[s])) continue;  // "x": muted
      const n = Number(frets[s]);
      found.push(strings[s] + up + (n ? n + base - 1 : 0));
    }
    return found;
  };
  const hz = (midi) => 440 * Math.pow(2, (midi - 69) / 12);
  const frequencies = (position, capo, tuning) => notes(position, capo, tuning).map(hz);

  // One plucked string: noise, softened (a one-pole low pass) and with no DC, fills the first period;
  // each sample after is a blend of two a period back (BLEND: the string's loss, more for higher
  // harmonics) times ``loss`` (its ring: lower notes ring longer), through an all-pass that tunes the
  // loop's delay to the period's fraction of a sample. The last 150 ms fade out, the first 2 ms in.
  const pluck = (frequency, rate, seconds, voice) => {
    const v = VOICES[voiceOf(voice)];
    const blend = v.kind === "pluck" ? v.blend : BLEND;
    const length = Math.max(1, Math.round(rate * seconds));
    const s = new Float32Array(length);
    const period = rate / frequency;
    const size = Math.max(2, Math.floor(period - blend - 0.1));  // the delay's whole samples; the rest is the all-pass's
    const fraction = period - blend - size;  // 0.1 to 1.1: the blend delays ``blend`` of a sample
    const c = (1 - fraction) / (1 + fraction);
    // Seconds to fall 60 dB: the guitar's, times the voice's ring.
    const ring = Math.min(6, Math.max(1.5, 6 * Math.pow(82.4 / frequency, 0.5))) * (v.kind === "pluck" ? v.ring : 1);
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
      const back = loss * ((1 - blend) * s[i - size] + blend * (i - size - 1 >= 0 ? s[i - size - 1] : 0));
      s[i] = c * back + before - c * s[i - 1];
      before = back;
    }
    const fadeIn = Math.min(length, Math.round(rate * 0.002));
    for (let i = 0; i < fadeIn; i++) s[i] *= i / fadeIn;
    const fadeOut = Math.min(length, Math.round(rate * 0.15));
    for (let i = 0; i < fadeOut; i++) s[length - 1 - i] *= i / fadeOut;
    return s;
  };

  // A piano's note: its partials (the string's harmonics, a little sharp as a stiff string's are: ``STIFF``), each
  // softer the higher it is and dying away faster, a higher note's faster too, as a damped resonator rings (two
  // multiplications a sample, no sine computed): struck in 3 ms, the last 150 ms faded out.
  const STIFF = 0.0002;
  const strike = (frequency, rate, seconds) => {
    const length = Math.max(1, Math.round(rate * seconds));
    const s = new Float32Array(length);
    for (let k = 1; k <= 12; k++) {
      const f = k * frequency * Math.sqrt(1 + STIFF * k * k);
      if (f > rate * 0.45) break;
      const w = (2 * Math.PI * f) / rate;
      const r = Math.exp(-((1.2 + 0.55 * k) * Math.pow(frequency / 261.63, 0.35)) / rate);  // its fall a sample
      const amplitude = Math.pow(k, -1.5) * (k === 1 ? 1 : 0.85);
      const a = 2 * r * Math.cos(w), b = -r * r;
      let y2 = 0, y1 = amplitude * r * Math.sin(w);  // each partial from its start: the same note every time
      s[0] += y2;
      if (length > 1) s[1] += y1;
      for (let i = 2; i < length; i++) {
        const y = a * y1 + b * y2;
        s[i] += y;
        y2 = y1;
        y1 = y;
      }
    }
    let top = 0;
    for (let i = 0; i < length; i++) top = Math.max(top, Math.abs(s[i]));
    if (top > 0) for (let i = 0; i < length; i++) s[i] /= top;
    const fadeIn = Math.min(length, Math.round(rate * 0.003));
    for (let i = 0; i < fadeIn; i++) s[i] *= i / fadeIn;
    const fadeOut = Math.min(length, Math.round(rate * 0.15));
    for (let i = 0; i < fadeOut; i++) s[length - 1 - i] *= i / fadeOut;
    return s;
  };

  // A note's buffer in a voice, kept for the next strum of it (a progression strums the same notes again and again).
  const buffers = new Map();
  const bufferOf = (midi, voice) => {
    const name = voiceOf(voice);
    const key = context.sampleRate + ":" + name + ":" + midi;
    let buffer = buffers.get(key);
    if (!buffer) {
      buffer = context.createBuffer(1, Math.round(context.sampleRate * RING), context.sampleRate);
      buffer.getChannelData(0).set(VOICES[name].kind === "strike" ? strike(hz(midi), context.sampleRate, RING)
        : pluck(hz(midi), context.sampleRate, RING, name));
      if (buffers.size >= 48) buffers.delete(buffers.keys().next().value);
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
  // A strum at ``at`` in a voice, string by string in their order (``up``: the other way), its notes ``gap`` apart (none
  // on the piano), the sounds before it stopped as it begins.
  const sound = (midis, at, level, up, voice) => {
    const v = VOICES[voiceOf(voice)];
    const order = up ? midis.slice().reverse() : midis;
    const made = order.map((midi) => bufferOf(midi, voice));
    silence(at);
    const gain = context.createGain();
    gain.gain.value = level;
    gain.connect(out);
    const which = { gain, sources: [], times: made.map((_, n) => at + n * v.gap), at, ends: Infinity };
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
    const o = options || {};
    const voice = voiceOf(o.voice);
    const midis = notes(position, o.capo, o.tuning);
    if (!midis.length || !ready()) return false;
    stop();
    whenRunning(() => {
      midis.forEach((midi) => bufferOf(midi, voice));  // made before the clock is read, so no string starts late
      sound(midis, context.currentTime + 0.005, VOICES[voice].level, false, voice);
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
    const chordNotes = list.map((chord) => (chord ? notes(chord.position, chord.capo, chord.tuning) : []));
    const chordVoices = list.map((chord) => voiceOf(chord && chord.voice));
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
        const midis = chordNotes[i], voice = chordVoices[i], level = VOICES[voice].level;
        midis.forEach((midi) => bufferOf(midi, voice));  // made before the clock is read: the first time, a note takes a while
        const soonest = context.currentTime + LEAD;
        if (timeOf(n) < soonest) origin += soonest - timeOf(n);  // late: the rest moves on with it
        const at = timeOf(n);
        if (b === 0) {
          if (midis.length) sound(midis, at, level, false, voice);
          else silence(at);  // a bar of silence
          bars.push([at, i]);
        } else if (midis.length) sound(midis, at, level * 0.62, (b / every) % 2 === 1, voice);
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
      chordNotes.forEach((midis, i) => midis.forEach((midi) => bufferOf(midi, chordVoices[i])));  // made before the first is timed
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
    notes, frequencies, strum, play, stop, setVolume, pluck, strike, voices: Object.freeze(Object.keys(VOICES)),
    available: Boolean(Context),
  });
})();
