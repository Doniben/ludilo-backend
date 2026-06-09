"""
Ludilo — Evaluación comparativa GP (ground truth) vs BP vs MT3+
Compara MIDI generados por Basic Pitch y YourMT3+ contra referencia Guitar Pro.
"""
import pretty_midi
import guitarpro
import mir_eval
import numpy as np
import json
from pathlib import Path

EVAL_DIR = Path("/tmp/ludilo-eval")
TICKS_PER_QUARTER = 960  # Guitar Pro standard


def ticks_to_seconds(ticks, tempo):
    """Convert GP ticks to seconds given tempo in BPM."""
    return (ticks / TICKS_PER_QUARTER) * (60.0 / tempo)


def gp_to_note_events(gp_path):
    """Extract note events from Guitar Pro file using tick-based timing.
    Returns dict of {track_type: [(onset_sec, offset_sec, midi_pitch), ...]}
    """
    song = guitarpro.parse(str(gp_path))
    tempo = song.tempo
    tracks = {}

    for track in song.tracks:
        # Classify track
        name_lower = track.name.lower()
        if track.isPercussionTrack:
            track_type = "drums"
        elif "bass" in name_lower or "newsted" in name_lower:
            track_type = "bass"
        elif "vocal" in name_lower or "voice" in name_lower or "vox" in name_lower:
            track_type = "vocals"
        elif "guitar" in name_lower or "gtr" in name_lower or "hetfield" in name_lower or "hammet" in name_lower or "kirk" in name_lower:
            track_type = "guitar"
        elif "symphony" in name_lower or "orchestra" in name_lower or "string" in name_lower:
            track_type = "other"
        elif "easy" in name_lower:
            continue  # Skip simplified tracks
        else:
            track_type = "other"

        notes = []

        for measure in track.measures:
            ts = measure.header.timeSignature
            measure_start_tick = measure.header.start  # absolute tick position

            for voice in measure.voices:
                current_tick = measure_start_tick
                for beat in voice.beats:
                    # Calculate beat duration in ticks
                    dur_value = beat.duration.value  # 1=whole, 2=half, 4=quarter, 8=eighth
                    beat_ticks = int(TICKS_PER_QUARTER * 4 / dur_value)

                    if beat.duration.isDotted:
                        beat_ticks = int(beat_ticks * 1.5)
                    if beat.duration.tuplet and beat.duration.tuplet.enters > 0:
                        beat_ticks = int(beat_ticks * beat.duration.tuplet.times / beat.duration.tuplet.enters)

                    # Check for tempo changes
                    if beat.effect and hasattr(beat.effect, 'mixTableChange') and beat.effect.mixTableChange:
                        mtc = beat.effect.mixTableChange
                        if mtc.tempo:
                            tempo = mtc.tempo.value

                    for note in beat.notes:
                        if note.type == guitarpro.NoteType.rest:
                            continue

                        midi_pitch = note.realValue if hasattr(note, 'realValue') else note.value

                        if note.type == guitarpro.NoteType.tie:
                            # Extend previous note with same pitch
                            for i in range(len(notes) - 1, -1, -1):
                                if notes[i][2] == midi_pitch:
                                    new_offset = ticks_to_seconds(current_tick + beat_ticks, tempo)
                                    notes[i] = (notes[i][0], new_offset, midi_pitch)
                                    break
                        else:
                            onset = ticks_to_seconds(current_tick, tempo)
                            offset = ticks_to_seconds(current_tick + beat_ticks, tempo)
                            notes.append((onset, offset, midi_pitch))

                    current_tick += beat_ticks

        if track_type not in tracks:
            tracks[track_type] = []
        tracks[track_type].extend(notes)

    return tracks, song


def midi_to_note_events(midi_path):
    """Extract note events from MIDI file."""
    try:
        pm = pretty_midi.PrettyMIDI(str(midi_path))
    except Exception as e:
        return []
    notes = []
    for instrument in pm.instruments:
        for note in instrument.notes:
            notes.append((note.start, note.end, note.pitch))
    return notes


def evaluate_notes(ref_notes, est_notes, onset_tolerance=0.1):
    """Compare estimated notes against reference using mir_eval."""
    if not ref_notes or not est_notes:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0,
                "ref_notes": len(ref_notes), "est_notes": len(est_notes)}

    ref_intervals = np.array([[n[0], n[1]] for n in ref_notes])
    ref_pitches = np.array([n[2] for n in ref_notes], dtype=float)
    est_intervals = np.array([[n[0], n[1]] for n in est_notes])
    est_pitches = np.array([n[2] for n in est_notes], dtype=float)

    ref_pitches_hz = mir_eval.util.midi_to_hz(ref_pitches)
    est_pitches_hz = mir_eval.util.midi_to_hz(est_pitches)

    precision, recall, f1, _ = mir_eval.transcription.precision_recall_f1_overlap(
        ref_intervals, ref_pitches_hz,
        est_intervals, est_pitches_hz,
        onset_tolerance=onset_tolerance,
        pitch_tolerance=50.0,
        offset_ratio=None
    )
    return {"precision": round(precision * 100, 2), "recall": round(recall * 100, 2),
            "f1": round(f1 * 100, 2), "ref_notes": len(ref_notes), "est_notes": len(est_notes)}


def pitch_class_accuracy(ref_notes, est_notes):
    """What % of estimated note pitch classes exist in the reference pitch class set."""
    if not ref_notes or not est_notes:
        return 0.0
    ref_pcs = set(n[2] % 12 for n in ref_notes)
    correct = sum(1 for n in est_notes if n[2] % 12 in ref_pcs)
    return round(correct / len(est_notes) * 100, 2)


def harmonic_consistency(notes, chords):
    """% of notes that fit the chord active at their onset time."""
    CHORD_NOTES = {
        "C": {0, 4, 7}, "Cm": {0, 3, 7}, "C7": {0, 4, 7, 10},
        "Cmaj7": {0, 4, 7, 11}, "C6": {0, 4, 7, 9}, "C/G": {0, 4, 7},
        "D": {2, 6, 9}, "Dm": {2, 5, 9}, "D7": {2, 6, 9, 0},
        "Dmaj7": {2, 6, 9, 1}, "D6": {2, 6, 9, 11},
        "E": {4, 8, 11}, "Em": {4, 7, 11}, "E7": {4, 8, 11, 2},
        "Em7": {4, 7, 11, 2},
        "G": {7, 11, 2}, "Gm": {7, 10, 2}, "G7": {7, 11, 2, 5},
        "G6": {7, 11, 2, 4}, "Gmaj7": {7, 11, 2, 6}, "G/D": {7, 11, 2},
        "A": {9, 1, 4}, "Am": {9, 0, 4}, "A7": {9, 1, 4, 7},
        "B": {11, 3, 6}, "Bm": {11, 2, 6}, "B7": {11, 3, 6, 9},
        "Bm7": {11, 2, 6, 9},
    }
    if not notes or not chords:
        return 0.0
    consistent = 0
    total = 0
    for note in notes:
        pc = note[2] % 12
        for chord in chords:
            if chord["start"] <= note[0] < chord["end"]:
                pcs = CHORD_NOTES.get(chord["label"])
                if pcs is not None:
                    if pc in pcs:
                        consistent += 1
                    total += 1
                break
    return round(consistent / max(total, 1) * 100, 2)


def hybrid_merge(bp_notes, mt3_notes, onset_tol=0.1):
    """Merge BP and MT3+ notes using intersection + MT3+-only strategy."""
    hybrid = []
    mt3_used = set()

    # Notes in both (intersection) → high confidence, use MT3+ timing
    for i, bp in enumerate(bp_notes):
        for j, mt3 in enumerate(mt3_notes):
            if abs(bp[0] - mt3[0]) < onset_tol and bp[2] == mt3[2]:
                hybrid.append(mt3)  # prefer MT3+ timing
                mt3_used.add(j)
                break

    # MT3+-only notes → add (MT3+ is conservative, likely real)
    for j, mt3 in enumerate(mt3_notes):
        if j not in mt3_used:
            hybrid.append(mt3)

    return hybrid


def main():
    print("=" * 70)
    print("LUDILO — Evaluación Comparativa: GP vs BP vs MT3+")
    print("Canción: Nothing Else Matters — Metallica")
    print("=" * 70)

    # Load GP
    print("\n📄 Cargando GP (ground truth)...")
    gp_tracks, song = gp_to_note_events(EVAL_DIR / "gp/nothing_else_matters.gp3")
    print(f"   Tempo: {song.tempo} BPM | Time sig: 6/8")
    print(f"   Pistas: {list(gp_tracks.keys())}")
    for t, n in gp_tracks.items():
        pitches = [x[2] for x in n]
        print(f"   {t}: {len(n)} notas (pitch range: {min(pitches) if pitches else 0}-{max(pitches) if pitches else 0})")

    # Load MIDIs
    print("\n🎵 Cargando MIDIs...")
    mt3, bp = {}, {}
    for stem in ["bass", "drums", "guitar", "vocals", "other"]:
        mt3[stem] = midi_to_note_events(EVAL_DIR / f"mt3/{stem}.mid")
        bp[stem] = midi_to_note_events(EVAL_DIR / f"bp/{stem}.mid")

    print(f"   MT3+: " + ", ".join(f"{s}={len(n)}" for s, n in mt3.items()))
    print(f"   BP:   " + ", ".join(f"{s}={len(n)}" for s, n in bp.items()))

    # Load chords
    chords = json.load(open(EVAL_DIR / "chords.json")) if (EVAL_DIR / "chords.json").exists() else None

    # --- Per-instrument evaluation ---
    print(f"\n{'═' * 70}")
    print("EVALUACIÓN POR INSTRUMENTO")
    print(f"{'═' * 70}")

    results = {}
    for instrument in ["guitar", "bass", "vocals", "other", "drums"]:
        ref = gp_tracks.get(instrument, [])
        if not ref:
            continue

        mt3_eval = evaluate_notes(ref, mt3.get(instrument, []))
        bp_eval = evaluate_notes(ref, bp.get(instrument, []))

        # Hybrid
        hybrid_notes = hybrid_merge(bp.get(instrument, []), mt3.get(instrument, []))
        hybrid_eval = evaluate_notes(ref, hybrid_notes)

        # Harmonic consistency
        mt3_harm = harmonic_consistency(mt3.get(instrument, []), chords) if chords else 0
        bp_harm = harmonic_consistency(bp.get(instrument, []), chords) if chords else 0
        hybrid_harm = harmonic_consistency(hybrid_notes, chords) if chords else 0

        print(f"\n{'─' * 60}")
        print(f"  {instrument.upper()} — Referencia GP: {len(ref)} notas")
        print(f"{'─' * 60}")
        print(f"  {'Metric':<22} {'MT3+':>8} {'BP':>8} {'Hybrid':>8} {'Best':>8}")
        print(f"  {'─' * 54}")

        f1s = {"MT3+": mt3_eval['f1'], "BP": bp_eval['f1'], "Hybrid": hybrid_eval['f1']}
        best_f1 = max(f1s, key=f1s.get)

        print(f"  {'Precision %':.<22} {mt3_eval['precision']:>8.1f} {bp_eval['precision']:>8.1f} {hybrid_eval['precision']:>8.1f}")
        print(f"  {'Recall %':.<22} {mt3_eval['recall']:>8.1f} {bp_eval['recall']:>8.1f} {hybrid_eval['recall']:>8.1f}")
        print(f"  {'F1 %':.<22} {mt3_eval['f1']:>8.1f} {bp_eval['f1']:>8.1f} {hybrid_eval['f1']:>8.1f} {best_f1:>8}")
        print(f"  {'Harmonic consist. %':.<22} {mt3_harm:>8.1f} {bp_harm:>8.1f} {hybrid_harm:>8.1f}")
        print(f"  {'Notes detected':.<22} {mt3_eval['est_notes']:>8} {bp_eval['est_notes']:>8} {len(hybrid_notes):>8}")

        pc_mt3 = pitch_class_accuracy(ref, mt3.get(instrument, []))
        pc_bp = pitch_class_accuracy(ref, bp.get(instrument, []))
        pc_hybrid = pitch_class_accuracy(ref, hybrid_notes)
        print(f"  {'Pitch class acc. %':.<22} {pc_mt3:>8.1f} {pc_bp:>8.1f} {pc_hybrid:>8.1f}")

        results[instrument] = {
            "ref_notes": len(ref),
            "mt3": {**mt3_eval, "harmonic": mt3_harm, "pitch_class": pc_mt3},
            "bp": {**bp_eval, "harmonic": bp_harm, "pitch_class": pc_bp},
            "hybrid": {**hybrid_eval, "harmonic": hybrid_harm, "pitch_class": pc_hybrid, "notes": len(hybrid_notes)},
            "winner_f1": best_f1
        }

    # --- Summary ---
    print(f"\n{'═' * 70}")
    print("RESUMEN")
    print(f"{'═' * 70}")
    for inst, r in results.items():
        print(f"  {inst:<10} → Best: {r['winner_f1']} (F1: MT3+={r['mt3']['f1']}% | BP={r['bp']['f1']}% | Hybrid={r['hybrid']['f1']}%)")

    # Save
    with open(EVAL_DIR / "results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n✅ Resultados: {EVAL_DIR / 'results.json'}")


if __name__ == "__main__":
    main()
