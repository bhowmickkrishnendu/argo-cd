from pathlib import Path
import re
import subprocess
import json
import yaml
from jsonschema import Draft7Validator

repo = Path.cwd()
out = repo / '.verification'
doc = (repo / 'docs/user-guide/helm.md').read_text(encoding='utf-8')
worked = doc.split('## Worked examples\n', 1)[1].split('## Values Files\n', 1)[0]
blocks = re.findall(r'```yaml\n(.*?)```', worked, re.S)
assert len(blocks) == 5, len(blocks)
default_app, inline_app, common, production, external_app = [yaml.safe_load(b) for b in blocks]
crd = yaml.safe_load((repo / 'manifests/crds/application-crd.yaml').read_text(encoding='utf-8'))
schema = next(v['schema']['openAPIV3Schema'] for v in crd['spec']['versions'] if v['name'] == 'v1alpha1')
for app in (default_app, inline_app, external_app):
    Draft7Validator(schema).validate(app)
assert 'source' not in external_app['spec']
chart_source, values_source = external_app['spec']['sources']
assert values_source['ref'] == 'values'
assert 'path' not in values_source
assert chart_source['chart'] == 'ingress-nginx'
assert chart_source['targetRevision'] == '4.11.3'
values_dir = out / 'values-repo/helm/ingress-nginx'
values_dir.mkdir(parents=True, exist_ok=True)
(values_dir / 'values-common.yaml').write_text(blocks[2], encoding='utf-8')
(values_dir / 'values-production.yaml').write_text(blocks[3], encoding='utf-8')
paths = []
for value_path in chart_source['helm']['valueFiles']:
    assert value_path.startswith('$values/')
    resolved = out / 'values-repo' / value_path.removeprefix('$values/')
    assert resolved.is_file(), resolved
    paths.append(resolved)

chart = out / 'ingress-nginx-4.11.3.tgz'
results = []
def render(case, expected_replicas, expected_type, expected_metrics, files=(), inline=None):
    cmd = ['helm', 'template', 'ingress-nginx', str(chart), '--namespace', 'ingress-nginx']
    for file in files:
        cmd += ['--values', str(file)]
    if inline is not None:
        file = out / 'inline-values.yaml'
        file.write_text(yaml.safe_dump(inline), encoding='utf-8')
        cmd += ['--values', str(file)]
    rendered = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    (out / f'{case}.yaml').write_text(rendered, encoding='utf-8')
    resources = [r for r in yaml.safe_load_all(rendered) if r]
    deploy = next(r for r in resources if r['kind'] == 'Deployment' and r['metadata']['name'] == 'ingress-nginx-controller')
    service = next(r for r in resources if r['kind'] == 'Service' and r['metadata']['name'] == 'ingress-nginx-controller')
    metrics = any(r['kind'] == 'Service' and r['metadata']['name'] == 'ingress-nginx-controller-metrics' for r in resources)
    assert deploy['spec']['replicas'] == expected_replicas, (case, deploy['spec']['replicas'])
    assert service['spec']['type'] == expected_type, (case, service['spec']['type'])
    assert metrics == expected_metrics, (case, metrics)
    result = dict(case=case, replicas=expected_replicas, service_type=expected_type, metrics=metrics)
    results.append(result)
    print(json.dumps(result))

render('chart-defaults', 1, 'LoadBalancer', False)
render('inline-values', 2, 'LoadBalancer', False, inline=inline_app['spec']['source']['helm']['valuesObject'])
render('shared-values', 1, 'ClusterIP', True, files=paths[:1])
render('production-values', 3, 'LoadBalancer', True, files=paths)
render('reversed-values', 1, 'ClusterIP', True, files=list(reversed(paths)))

# Check the actual built page, including the preserved section anchor and new local links.
html = (repo / 'site/user-guide/helm/index.html').read_text(encoding='utf-8')
assert 'id="values-file-from-another-git-repository"' in html
for expected in ('values-common.yaml', 'values-production.yaml', '../private-repositories/#credentials', '../projects/', '../application-set/'):
    assert expected in html, expected
assert not re.search(r'WARNING.*helm\.md', (out / 'mkdocs-build.log').read_text(encoding='utf-8'))
print('PASS: three Application manifests validated against the checked-out Application CRD.')
print('PASS: five Helm renders verified, including reversed file precedence.')
print('PASS: built page contains example files, preserved anchor, and local links.')
(out / 'validation-results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
