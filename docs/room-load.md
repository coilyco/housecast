# Room load test

`just room-load-test` holds a dev or rehearsal room under simulated attendees
(teable:coilyco/housecast#8488). It writes to the room's log, so reset that log
afterward, and never point it at the live room.

## A round

Each attendee is an SSE client with its own device token. The presenter opens
submissions, all attendees submit at once, the room answers and scores, the
presenter picks a prompt, all attendees grade at once, and the split shows. The
default is 30 attendees and three rounds.

It fails the run when a client misses a page swap, skips a `rev`, never sees the
grade count, sees the split while grading is open, or gets a split that does not
match the grades sent. A failed answer fails it too, unless `--allow-failed-answers`
says how many to tolerate.

Per subject and round it measures queue wait, run time and total time (p50, p95, max),
failure reasons, lexical fallbacks, peak answers running, and each page swap's reach time.

```
just room-load-test --base https://room.example --token-file /path/token --writes
```

The token comes from a 0600 file, never argv. The report is `dist/room-load-test/report.json`.

## The restart drill

`--pause-at answering` or `grading` stops at a checkpoint in round `--pause-round`
and waits for a `RESUME` file. The operator restarts the room at the same address,
then creates the file. The run checks that the phase, rounds, finished answers and
grades survived, that cut-off answers were asked again, and that every client
caught up. The script never touches the pod.

## Limits

The room allows 30 prompts per viewer address per window, so 30 clients from one
machine sit exactly at the ceiling, and `--round-gap` defaults to 21 seconds. The
engine runs 40 answers at once, so 30 attendees ask 120 and the rest queue.
