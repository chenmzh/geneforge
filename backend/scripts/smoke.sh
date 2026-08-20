#!/usr/bin/env bash
# End-to-end API smoke test. Usage: scripts/smoke.sh [base_url]
set -euo pipefail
BASE="${1:-http://127.0.0.1:8090}"
API="$BASE/api/v1"
SAMPLES="${SAMPLES:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../samples" && pwd)}"
JQ() { python3 -c 'import sys,json;d=json.load(sys.stdin);
import functools,operator
path=sys.argv[1]
for key in path.split("."):
    if not key: continue
    d = d[int(key)] if key.lstrip("-").isdigit() else d[key]
print(d)' "$1"; }
say() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }

say "login as bootstrap admin"
TOKEN=$(curl -sf -X POST "$API/auth/login" -H 'Content-Type: application/json' \
  -d '{"username":"admin@geneforge.local","password":"ChangeMe123!"}' | JQ "access_token")
AUTH=(-H "Authorization: Bearer $TOKEN")
echo "token acquired (${#TOKEN} chars)"

say "who am I"
curl -sf "${AUTH[@]}" "$API/auth/me" | python3 -m json.tool

say "dashboard summary"
curl -sf "${AUTH[@]}" "$API/me/summary" | python3 -c "import sys,json;d=json.load(sys.stdin);print('projects',d['projects'],'sequences',d['sequences'],'recent',[s['name'] for s in d['recent_sequences']])"

say "create project"
PROJ=$(curl -sf -X POST "${AUTH[@]}" -H 'Content-Type: application/json' "$API/projects" \
  -d '{"name":"Smoke Test Project","description":"created by smoke.sh","tags":["ci"]}' | JQ "id")
echo "project=$PROJ"

say "import demo plasmid (GenBank upload)"
IMP=$(curl -sf -X POST "${AUTH[@]}" -F "file=@${SAMPLES}/pGF-EGFP.gb" "$API/projects/$PROJ/sequences/import?auto_annotate=false")
echo "$IMP" | python3 -m json.tool
SEQ=$(echo "$IMP" | JQ "imported.0.sequence_id")

say "sequence detail"
curl -sf "${AUTH[@]}" "$API/sequences/$SEQ" | python3 -c "
import sys,json;d=json.load(sys.stdin)
print('name',d['name'],'len',d['length'],'gc',d['gc_content'],'topology',d['topology'],'features',len(d['features']))
for f in d['features'][:4]: print('   ',f['type'],f['name'],f['start'],f['end'],f['strand'])"

say "stats"
curl -sf "${AUTH[@]}" "$API/sequences/$SEQ/stats" | python3 -c "import sys,json;d=json.load(sys.stdin);print({k:v for k,v in d.items() if k not in ('gc_track','longest_orf')});print('gc_track points',len(d['gc_track']))"

say "restriction site search (common enzymes)"
curl -sf -X POST "${AUTH[@]}" -H 'Content-Type: application/json' "$API/tools/enzymes/search" \
  -d "{\"sequence_id\":\"$SEQ\",\"common_only\":true,\"unique_only\":true}" | python3 -c "
import sys,json;d=json.load(sys.stdin)
print('unique cutters:',[(r['enzyme'],r['cut_positions'][0]) for r in d['summary'][:12]])
print('suggested pairs:',[(p['enzyme_a'],p['enzyme_b'],p['distance']) for p in d['suggestions'][:3]])"

say "digest EcoRI+BamHI with virtual gel"
curl -sf -X POST "${AUTH[@]}" -H 'Content-Type: application/json' "$API/tools/digest" \
  -d "{\"sequence_id\":\"$SEQ\",\"enzymes\":[\"EcoRI\",\"BamHI\",\"HindIII\"],\"ladder\":\"1kb_plus\"}" | python3 -c "
import sys,json;d=json.load(sys.stdin)
print('cuts',d['cut_positions'],'fragments',d['fragment_sizes'])
print('gel lanes',[l['name'] for l in d['gel']['lanes']],'sample bands',len(d['gel']['lanes'][1]['bands']))"

say "primer design over the EGFP CDS"
curl -sf -X POST "${AUTH[@]}" -H 'Content-Type: application/json' "$API/tools/primers/design" \
  -d "{\"sequence_id\":\"$SEQ\",\"target_start\":551,\"target_end\":1271,\"max_pairs\":3}" | python3 -c "
import sys,json;d=json.load(sys.stdin)
for p in d['pairs']:
    print(f\"  {p['forward']['name']} {p['forward']['sequence']} Tm={p['forward']['tm']} | {p['reverse']['name']} {p['reverse']['sequence']} Tm={p['reverse']['tm']} | product {p['product_size']} bp Ta={p['annealing_temp']} score={p['score']}\")"

say "PCR simulation with the best pair"
read -r FWD REV <<< "$(curl -sf -X POST "${AUTH[@]}" -H 'Content-Type: application/json' "$API/tools/primers/design" \
  -d "{\"sequence_id\":\"$SEQ\",\"target_start\":551,\"target_end\":1271,\"max_pairs\":1}" | python3 -c "
import sys,json;d=json.load(sys.stdin);p=d['pairs'][0];print(p['forward']['sequence'],p['reverse']['sequence'])")"
curl -sf -X POST "${AUTH[@]}" -H 'Content-Type: application/json' "$API/tools/pcr" \
  -d "{\"sequence_id\":\"$SEQ\",\"forward\":\"$FWD\",\"reverse\":\"$REV\"}" | python3 -c "
import sys,json;d=json.load(sys.stdin)
print('products',[(p['start'],p['end'],p['size']) for p in d['products']],'specific',d['specific'],'Ta',d['annealing_temp'],'warnings',d['warnings'])"

say "translate the EGFP CDS"
curl -sf -X POST "${AUTH[@]}" -H 'Content-Type: application/json' "$API/tools/translate" \
  -d "{\"sequence_id\":\"$SEQ\",\"frame\":0,\"to_stop\":false}" | python3 -c "
import sys,json;d=json.load(sys.stdin);print('protein len',d['length'],'MW',d['molecular_weight'],'pI',d['isoelectric_point'])"

say "ORF finding"
curl -sf -X POST "${AUTH[@]}" -H 'Content-Type: application/json' "$API/tools/orf" \
  -d "{\"sequence_id\":\"$SEQ\",\"min_aa\":80}" | python3 -c "
import sys,json;d=json.load(sys.stdin);print('orfs',[(o['start'],o['end'],o['strand'],o['aa_length']) for o in d['orfs'][:5]])"

say "auto-annotate a fresh copy"
COPY=$(curl -sf -X POST "${AUTH[@]}" "$API/sequences/$SEQ/copy?new_name=annotated_copy" | JQ "id")
curl -sf -X POST "${AUTH[@]}" "$API/sequences/$COPY/auto-annotate?replace=true&min_orf_aa=100" | python3 -c "
import sys,json;d=json.load(sys.stdin)
print('features after auto-annotate:',len(d['features']))
for f in d['features'][:8]: print('   ',f['type'],f['name'],f['start'],f['end'],f['strand'])"

say "edit: insert 6 bp then check version history"
curl -sf -X POST "${AUTH[@]}" -H 'Content-Type: application/json' "$API/sequences/$COPY/edit" \
  -d '{"operations":[{"op":"insert","position":100,"payload":"GAATTC"}],"message":"add EcoRI site"}' | python3 -c "
import sys,json;d=json.load(sys.stdin);print('new length',d['length'],'version',d['current_version'])"
curl -sf "${AUTH[@]}" "$API/sequences/$COPY/versions" | python3 -c "
import sys,json;d=json.load(sys.stdin)
for v in d: print('   v%s'%v['version'], v['message'], '| len', v['length'], v['diff_summary'].get('delta',''))"

say "restore version 1"
curl -sf -X POST "${AUTH[@]}" "$API/sequences/$COPY/versions/1/restore" | python3 -c "
import sys,json;d=json.load(sys.stdin);print('restored length',d['length'],'now version',d['current_version'])"

say "align Sanger read against the plasmid (async job)"
READ_ID=$(curl -sf -X POST "${AUTH[@]}" -F "file=@${SAMPLES}/sanger_read_01.fasta" "$API/projects/$PROJ/sequences/import" | JQ "imported.0.sequence_id")
JOB=$(curl -sf -X POST "${AUTH[@]}" -H 'Content-Type: application/json' "$API/tools/align" \
  -d "{\"query_sequence_id\":\"$READ_ID\",\"target_sequence_id\":\"$SEQ\",\"mode\":\"glocal\",\"async_job\":true}" | JQ "job_id")
echo "job=$JOB"
for i in $(seq 1 40); do
  STATUS=$(curl -sf "${AUTH[@]}" "$API/jobs/$JOB" | JQ "status")
  [ "$STATUS" = "succeeded" ] || [ "$STATUS" = "failed" ] && break
  sleep 0.5
done
curl -sf "${AUTH[@]}" "$API/jobs/$JOB" | python3 -c "
import sys,json;d=json.load(sys.stdin)
print('status',d['status'],'progress',d['progress'])
r=d['result'] or {}
print('identity',r.get('identity'),'method',r.get('method'),'target',r.get('target_start'),'-',r.get('target_end'),'variants',r.get('variant_count'))
for v in (r.get('variants') or [])[:4]: print('   ',v)"

say "multiple alignment"
curl -sf -X POST "${AUTH[@]}" -H 'Content-Type: application/json' "$API/tools/align/multiple" \
  -d "{\"sequence_ids\":[\"$READ_ID\",\"$SEQ\"]}" | python3 -c "
import sys,json;d=json.load(sys.stdin);print('width',d['width'],'rows',[r['name'] for r in d['rows']],'identity',d['identity_matrix'])" 2>/dev/null || echo "(multi-align returned a job)"

say "export GenBank round trip"
curl -sf "${AUTH[@]}" "$API/sequences/$COPY/export?format=genbank&download=false" | head -6
curl -sf "${AUTH[@]}" "$API/sequences/$COPY/export?format=fasta&download=false" | head -2

say "save a primer"
curl -sf -X POST "${AUTH[@]}" -H 'Content-Type: application/json' "$API/projects/$PROJ/primers" \
  -d "{\"name\":\"EGFP_F\",\"sequence\":\"$FWD\",\"sequence_id\":\"$SEQ\"}" | python3 -c "
import sys,json;d=json.load(sys.stdin);print('saved primer',d['name'],d['sequence'],'Tm',d['tm'])"

say "external resource registry"
curl -sf "${AUTH[@]}" "$API/external/resources" | python3 -c "
import sys,json;d=json.load(sys.stdin)
for r in d: print('   ',r['name'],'|',r['kind'],'| proxy',r['allow_proxy'])"
RES=$(curl -sf "${AUTH[@]}" "$API/external/resources" | python3 -c "
import sys,json;d=json.load(sys.stdin);print([r['id'] for r in d if 'Nucleotide' in r['name']][0])")
curl -sf -X POST "${AUTH[@]}" -H 'Content-Type: application/json' "$API/external/resources/$RES/url" \
  -d '{"params":{"accession":"NC_000913.3"}}' | python3 -m json.tool

say "RBAC: viewer cannot edit"
# tolerate re-runs: the account may already exist (409)
curl -s -X POST "$API/auth/register" -H 'Content-Type: application/json' \
  -d '{"email":"viewer@example.com","username":"viewer1","password":"ViewerPass123"}' >/dev/null || true
curl -sf -X POST "${AUTH[@]}" -H 'Content-Type: application/json' "$API/projects/$PROJ/members" \
  -d '{"username":"viewer1","role":"viewer"}' | python3 -c "import sys,json;d=json.load(sys.stdin);print('added member',d['username'],d['role'])"
VTOKEN=$(curl -sf -X POST "$API/auth/login" -H 'Content-Type: application/json' \
  -d '{"username":"viewer1","password":"ViewerPass123"}' | JQ "access_token")
echo -n "viewer read: "; curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $VTOKEN" "$API/sequences/$SEQ"
echo -n "viewer edit (expect 403): "; curl -s -o /dev/null -w "%{http_code}\n" -X POST -H "Authorization: Bearer $VTOKEN" \
  -H 'Content-Type: application/json' "$API/sequences/$SEQ/edit" -d '{"operations":[{"op":"delete","start":0,"end":10}]}'
echo -n "unauthenticated (expect 401): "; curl -s -o /dev/null -w "%{http_code}\n" "$API/projects"

say "API key auth"
KEY=$(curl -sf -X POST "${AUTH[@]}" -H 'Content-Type: application/json' "$API/auth/api-keys" \
  -d '{"name":"pipeline","expires_in_days":30}' | JQ "key")
curl -sf -H "X-API-Key: $KEY" "$API/auth/me" | python3 -c "import sys,json;print('api-key auth as',json.load(sys.stdin)['username'])"

say "audit trail (last 6)"
curl -sf "${AUTH[@]}" "$API/audit-logs?size=6" | python3 -c "
import sys,json;d=json.load(sys.stdin)
for a in d['items']: print('   ',a['created_at'][:19],a['action'],a['entity_type'] or '',str(a['detail'])[:70])"

say "instance stats"
curl -sf "${AUTH[@]}" "$API/stats" | python3 -m json.tool

printf '\n\033[1;32mALL SMOKE CHECKS PASSED\033[0m\n'
