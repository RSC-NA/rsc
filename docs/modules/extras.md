# Extras

**Package:** [rsc/extras/](../../rsc/extras/) · **Mixin(s):** `ExtrasMixIn`

Small fun commands for the community: a magic 8 ball, a dice roll, and rock paper scissors. They have no league function.

## Using it

Anyone can run them in a server channel. Replies are public.

## Commands

| Command | Who can run it | What it does |
|---|---|---|
| `/8ball question` | Anyone | Answers with one of 20 magic 8 ball replies. The question must end with `?`. |
| `/roll [number]` | Anyone | Random number from 1 to `number` (default 100). `number` must be above 1 and at most 2^63 - 1. |
| `/rps your_choice` | Anyone | Rock, paper or scissors against the bot. |

## Configuration

None.

## Background work

None.

## How it works

- [extras.py](../../rsc/extras/extras.py): `ExtrasMixIn` and the three commands. Randomness comes from Python's `random` module. No API calls.
