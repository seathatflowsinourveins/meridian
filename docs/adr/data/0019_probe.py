"""Offline pinned-hook probe. ROOT is the disposable installation from 0019-stack.md.

Uses synthetic transcript evidence only: this tests scheduling, not model performance.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

root = Path(sys.argv[1]).resolve()
repo = Path(__file__).resolve().parents[3]
home = root / 'claude'
work = root / 'work'
profile = work / '.claude/omc.jsonc'
profile.parent.mkdir(parents=True, exist_ok=True)
profile.write_text((repo / '.claude/omc.jsonc').read_text())
env = dict(os.environ, CLAUDE_CONFIG_DIR=str(home), XDG_CONFIG_HOME=str(root / 'config'),
           OMC_HOME=str(root / 'omc-home'), OMC_STATE_DIR=str(root / 'state'))
session = 'probe-' + uuid.uuid4().hex
transcript = home / 'projects/synthetic' / (session + '.jsonl')
transcript.parent.mkdir(parents=True, exist_ok=True)
transcript.write_text('')
data = {'cwd': str(work), 'session_id': session, 'transcript_path': str(transcript)}
results = {}

def hook(event, name, fields):
    result = subprocess.run(
        [sys.executable, str(repo / 'deploy/wsl/meridian-omc.py'), 'hook', event,
         str(home / 'hooks' / name)], input=json.dumps(data | fields),
        text=True, capture_output=True, env=env, cwd=work, check=True)
    return json.loads(result.stdout) if result.stdout.strip() else {}

plain = hook('UserPromptSubmit', 'keyword-detector.mjs',
             {'prompt': 'build me a tool, code review, search the codebase, think hard'})
assert 'hookSpecificOutput' not in plain
results['prose_has_no_trigger'] = True
activation = hook('UserPromptSubmit', 'keyword-detector.mjs',
                  {'prompt': '/autopilot --workflow meridian-full implement a fake fixture'})
assert 'PIPELINE STAGE: RALPLAN' in activation['hookSpecificOutput']['additionalContext']
results['profile_activated'] = True
assert hook('Stop', 'persistent-mode.mjs', {'last_assistant_message': 'May I cross a boundary?'}) == {}
results['owner_question_releases_stop'] = True
hook('PostToolUse', 'post-tool-use.mjs', {'tool_input': {'command':
     'orca orchestration ask --question "Boundary decision"'}, 'tool_name': 'Bash'})
assert hook('Stop', 'persistent-mode.mjs', {'last_assistant_message': 'Handoff sent.'}) == {}
results['orca_ask_releases_stop'] = True
hook('UserPromptSubmit', 'keyword-detector.mjs', {'prompt': 'Reply: resume within scope'})
for index, stage in enumerate(['ralplan', 'execution', 'ralph', 'qa']):
    with transcript.open('a') as f:
        f.write(json.dumps({'sessionId': session, 'type': 'assistant', 'message': {
            'role': 'assistant', 'content': [{'type': 'text',
            'text': 'Signal: PIPELINE_' + stage.upper() + '_COMPLETE'}]}}) + '\n')
    response = hook('Stop', 'persistent-mode.mjs', {'last_assistant_message': 'Stage finished.'})
    assert response['decision'] == 'block'
    state = json.loads((root / 'state/non-git/state/sessions' / session / 'autopilot-state.json').read_text())
    assert state['pipelineTracking']['currentStageIndex'] == index + 1
    hook('Stop', 'persistent-mode.mjs', {'last_assistant_message': 'No new stage evidence.'})
    same = json.loads((root / 'state/non-git/state/sessions' / session / 'autopilot-state.json').read_text())
    assert same['pipelineTracking']['currentStageIndex'] == index + 1
    results[stage + '_advanced_once'] = True
assert state['phase'] == 'complete' and state['active'] is False
results['complete_is_inactive'] = True
assert hook('Stop', 'persistent-mode.mjs', {'last_assistant_message': 'Finished.'}).get('decision') != 'block'
results['next_stop_released'] = True
print(json.dumps(results, indent=2))
