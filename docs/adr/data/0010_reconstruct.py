"""Rebuild dsh-gungnir 0.2.1 model-visible texts from the pinned source
(Jonah-Wu23/dsh-gungnir@301255aeb71c6c15c28d150a94580df59e8761aa).
Every literal below is copied from the source file named beside it.
Writes UTF-8, LF, no trailing newline (the plugin joins lines with '\n' and
sends the string as one text block). Usage: py -3 -I reconstruct.py OUTDIR
"""
import json
import os
import sys

out = sys.argv[1]
os.makedirs(out, exist_ok=True)

# packages/core/src/passive.ts L580-587 buildMafMessage
MAF_HEAD = 'Evidence conflicts with completing this task:'
MAF_TAIL = ('Resolve the conflicts above before claiming completion (if the goal is already complete, '
            'fix the underlying issue or state the resolving evidence in your reply).')


def maf(lines):
    return '\n'.join([MAF_HEAD] + ['- ' + l for l in lines] + [MAF_TAIL])


# passive.ts L524 (assessContractCriteria detail, not blocked)
def vfail(code, expected=0):
    return f'verification command failed (exit {code}, expected {expected})'


# passive.ts L570 MAF_BY_KIND['test-failure'] with ref from L183 `call:${callId}#tool:${name}`
CALL_ID = 'call_00_q7Xk2Lm9Pz4Rt8Vw1Ny6Bc3D'  # placeholder, 24 chars after call_00_


def test_failure_line(call_id=CALL_ID, tool='bash'):
    return f'your most recent test run failed (call:{call_id}#tool:{tool}). Fix the failing test before claiming completion.'


# escalation.ts L267-281
def sig2(sig, n):
    return (f'The same command has failed {n} consecutive times with the same error ({sig}). '
            'Re-check the command itself and the environment before retrying — repeating the identical action will not change the outcome.')


def sig2_recover(sig, n):
    return (f'The same failure ({sig}) has persisted after {n} attempts. Stop repeating the current approach: '
            'step back, re-read the task specification, and switch to a different strategy before continuing.')


def sig3(n):
    return (f'You have re-read the same file content {n} times without any change. If you are chasing an error reported '
            'elsewhere, the source of that error is probably not this file — look at the component that actually produces the reported symptom.')


def sig4(n):
    return (f'You have gone {n} consecutive steps without any tool action producing a result. Take the next action now '
            '(run a command, read a file, or make a change) to make progress.')


# packages/dsh-plugin/src/prestep.ts L70-75
RECOVER = '\n'.join([
    'Your current approach has not been converging.',
    'Stop and re-assess: form a fresh hypothesis about what is actually wrong, and switch to a different strategy. Do not repeat the same failing action.',
])

# surfaces.ts L104-107, L158-161
CMDS = [
    ('ultragoal', 'Declare a versioned goal spec and let Gungnir drive it to verified completion (Declare it. Gungnir never misses.)'),
    ('gungnir', 'Inspect or control the Gungnir reconcile loop: status | verdicts | pause | resume | clear'),
]

# surfaces.ts L203-317 (passive='off' only)
TOOLS = [
    {
        'name': 'gungnir_submit_spec',
        'description': 'Submit a drafted GoalSpec for one-shot human confirmation. On approval Gungnir commits it and arms the native goal.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'spec': {'type': 'object', 'description': 'Complete GoalSpec object (specId, version, objective, successCriteria[] each {id, description, predicate{kind,...}, verifierLevel}, constraints, nonGoals, assumptions, budget). predicate kinds: exit_code(L1) | artifact(L2) | llm_rubric(L4, REQUIRES subjectPath naming the artifact to judge) | human(L5)', 'additionalProperties': True},
            },
            'required': ['spec'],
        },
    },
    {
        'name': 'gungnir_plan',
        'description': "Submit a rolling-horizon projection. The harness commits the first actionable step as this round's single action.",
        'input_schema': {
            'type': 'object',
            'properties': {
                'rationale': {'type': 'string', 'description': 'Why this projection now (esp. after REPLAN)'},
                'steps': {
                    'type': 'array',
                    'description': 'Ordered steps; the harness commits the first one with unsatisfied targets.',
                    'items': {
                        'type': 'object',
                        'additionalProperties': False,
                        'properties': {
                            'id': {'type': 'string', 'description': 'Stable step id, e.g. s1'},
                            'summary': {'type': 'string', 'description': 'Imperative one-liner for the committed round'},
                            'targetsCriteria': {'type': 'array', 'description': 'Success criterion ids this step aims to satisfy', 'items': {'type': 'string'}},
                            'expectedEvidence': {'type': 'array', 'description': 'Evidence hints (paths/commands)', 'items': {'type': 'string'}},
                        },
                        'required': ['id', 'summary', 'targetsCriteria'],
                    },
                },
            },
            'required': ['rationale', 'steps'],
        },
    },
    {
        'name': 'gungnir_report',
        'description': 'Report your outcome for the committed action. This is a CLAIM — verdicts come only from harness-verified evidence.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'summary': {'type': 'string', 'description': 'What you did and observed'},
                'asserted_outcome': {'type': 'string', 'description': 'done | partial | failed | blocked'},
                'evidence_refs': {'type': 'array', 'description': 'evidenceIds you believe support the claim', 'items': {'type': 'string'}},
            },
            'required': ['summary', 'asserted_outcome'],
        },
    },
]

# prestep.ts L9-35, first step of round 1 (no committed action), 4 criteria, none PASS
DIRECTIVE_R1 = '\n'.join([
    '[Round 1 start] No action is committed yet. Call the gungnir_plan tool ONCE with a rolling-horizon projection (ordered steps, each targeting concrete successCriteria). The harness will commit the first actionable step for this round.',
    'Success criteria: 0/4 verified PASS (none yet). Never redo an already-PASS criterion.',
    'Discipline: your reports are CLAIMS, not evidence — the harness verifies through gungnir/evidence and issues verdicts. When the action is done, call gungnir_report(summary, asserted_outcome) with an honest outcome.',
    'Termination: when ALL criteria are verified (the harness will tell you), call update_goal(action="complete"). If genuinely stuck, call update_goal(action="blocked"). Never claim completion without verification.',
])

# engine.ts L370 and L363
COMPLETE = 'Gungnir: every success criterion re-verified PASS with deterministic evidence. Call update_goal(action="complete") now — claims are already backed by the ledger.'
REPLAN = 'Gungnir: the current projection premise failed. Call gungnir_plan with a corrected projection (rationale required); do not redo criteria that already PASS.'

files = {
    'always-on-default-bpar-EMPTY.txt': '',
    'bpar-maf-r2-one-l1-failed.txt': maf([vfail(1)]),
    'bpar-maf-r2-four-l1-exit-minus1-on-dsh-0.2.2.txt': maf([vfail(-1)] * 4),
    'bpar-maf-s1-test-failure.txt': maf([test_failure_line()]),
    'bpar-sig2-maf.txt': sig2('bash:failure', 3),
    'bpar-sig2-recover-text.txt': sig2_recover('bash:failure', 5),
    'bpar-sig3-maf.txt': sig3(3),
    'bpar-sig4-maf.txt': sig4(8),
    'unreachable-recover-directive.txt': RECOVER,
    'ui-only-commands-listing.txt': '\n'.join(f'- {n}: {d}' for n, d in CMDS),
    'off-mode-tools-listing.txt': '\n'.join(f"- {t['name']}: {t['description']}" for t in TOOLS),
    'off-mode-tools-schema-approx.json': json.dumps(TOOLS, ensure_ascii=False, separators=(',', ':')),
    'off-mode-directive-round1-every-step.txt': DIRECTIVE_R1,
    'off-mode-engine-complete-directive.txt': COMPLETE,
    'off-mode-engine-replan-directive.txt': REPLAN,
    # extra texts the assessment did not reconstruct
    'extra-bpar-maf-r2-four-l1-exit1.txt': maf([vfail(1)] * 4),
    'extra-bpar-maf-write-outside-workspace.txt': maf(['a file was written outside the workspace (call:' + CALL_ID + '#tool:write#path:/tmp/notes.txt). Keep all output inside the workspace.']),
}
for name, text in files.items():
    with open(os.path.join(out, name), 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text)
    print(name, len(text))
