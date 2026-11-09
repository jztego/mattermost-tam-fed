# Mattermost TAM (FED) lab

Local Mattermost Enterprise on Kubernetes, on an Apple Silicon Mac Mini, for the Technical Account Manager interview project.

## For a reviewer

| The brief | Where to look |
| --- | --- |
| Mattermost on Kubernetes | Operator install in `scripts/bootstrap.sh`, server in `deploy/mattermost.yaml` |
| LDAP group that can be @-mentioned | `ship_crew` in channel `bridge`. Fry, Leela, and Bender are the members |
| A channel message from an incoming webhook | Channel `alerts`. `scripts/workspace.py` creates the hook and posts |
| SQL behind System Console > Site Statistics > Total Sessions | [docs/total-sessions.md](docs/total-sessions.md) |

A live walkthrough is: port-forward, log in as `sysadmin`, show `@ship_crew` in `bridge`, post the webhook into `alerts`, then open System Console > Site Statistics and compare Total Sessions with the SQL in that doc.

This is a lab on one machine. It is not a customer deployment. The section under License says what that difference is.

The server is Mattermost **11.7.15**, the current extended-support release. It runs through the Mattermost Operator, which is the Kubernetes path in the public deployment guide:

https://docs.mattermost.com/deployment-guide/server/kubernetes/deploy-k8s

## What is running

| Piece | Where | Notes |
| --- | --- | --- |
| Cluster | Colima k3s `v1.35.0+k3s1` | 6 CPU, 12 GiB RAM, 40 GiB disk, Rosetta on |
| Ingress | ingress-nginx | ClusterIP. The node IP is not routed to the Mac, so the browser path is a port-forward |
| Operator | chart `1.0.5`, image `v1.25.4` | Latest chart on `https://helm.mattermost.com` |
| Mattermost | `mattermost/mattermost-enterprise-edition:11.7.15` | One replica. Image is amd64 only |
| Database | `postgres:16-alpine` in-cluster | The guide's external database, pointed at this service |
| Files | MinIO `bitnamilegacy/minio` (app 2025.5.24), bucket `mattermost` | `minio/minio` is no longer anonymously pullable on Docker Hub |
| Directory | `ghcr.io/rroemhild/docker-test-openldap:master` | The image linked from the interview PDF. amd64 only |

Open the workspace at http://127.0.0.1:8065 after:

```bash
kubectl -n mattermost port-forward svc/mm 8065:8065
```

Lab logins, local to this cluster only:

| Who | Username | Password |
| --- | --- | --- |
| System admin | `sysadmin` | `LabAdmin!2026mm` |
| LDAP crew | `fry`, `leela`, `bender` | same as the username |
| LDAP bind | `cn=admin,dc=planetexpress,dc=com` | `GoodNewsEveryone` |

Team `planet-express`. Channel `bridge` is where `@ship_crew` is mentioned. Channel `alerts` receives the incoming webhook.

## License

The 11.7.15 Enterprise image, with no license file, enables **Mattermost Entry** on its own. On this boot the log recorded `ldap=true`, `ldap_groups=true`, and an expiry of 2027-02-17. That is the license the LDAP group work and the Total Sessions panel are using.

A trial request was also made, because the brief says to request one:

- `POST /api/v4/trial-license` with a full company payload was rejected: `Invalid business email` for a personal Gmail address. The license server wants a business address.
- The legacy payload (`users`, `terms_accepted`, `receive_emails_accepted` only) came back `500` from Mattermost's license service.

Entry is enough for every feature this project exercises. A business email would be the next step if a named trial key is required.

For a customer, especially an air-gapped one, that trial call would not be made. The license would be a file applied offline. Entry also does not include high availability, which is why the server log says it is not licensed for High Availability. The process still serves.

Two other lab shortcuts are in the manifests on purpose, so the steps can be repeated from this repo:

- Database, MinIO, and admin passwords are in the YAML and in the table above. On a customer system those would come from a secret store, not from Git.
- LDAP is plain LDAP on port 10389 inside the cluster, using the bind account published with the interview image. A customer connection would be LDAPS, with a bind account that is not in the repo.

## One-time cluster

```bash
brew install kubectl helm
colima start --kubernetes --cpu 6 --memory 12 --disk 40 --vz-rosetta
./scripts/bootstrap.sh
kubectl -n mattermost port-forward svc/mm 8065:8065
python3 scripts/workspace.py
```

`workspace.py` writes `secrets/admin.env` on first run if it is missing, and creates `sysadmin` when the database has no users yet. LDAP can already be on. The first account through `/api/v4/users` becomes the system admin. Keep the port-forward running in another terminal before that script.

`bootstrap.sh` installs ingress-nginx and the Operator from the Helm repos in the deployment guide, pulls the two amd64-only images with `--platform linux/amd64`, then applies `deploy/`.

The installed Operator CRD is v1.25.4. It does not have the `spec.database.readinessCheck` field described on the current docs page, so the manifest keeps the legacy database check (`DB_CONNECTION_CHECK_URL` plus the `postgres:13` init container). Replicas are set to 1 and the app is capped at 3 GiB so a 12 GiB node can schedule it. Omitting both lets the Operator apply the 5000-user size.

## LDAP group sync

Directory data comes from the interview image: base `dc=planetexpress,dc=com`, group `cn=ship_crew` (`objectClass: Group`) with `member` DNs for Fry, Leela, and Bender.

Mattermost LDAP settings are on the Operator manifest (`MM_LDAPSETTINGS_*`):

- Server `openldap.mattermost.svc.cluster.local` port `10389`, no TLS
- User filter `(objectClass=inetOrgPerson)`
- Group filter `(objectClass=Group)`
- Group id and display name `cn`
- Login and id attribute `uid`

`POST /api/v4/ldap/test` returned 200. Fry, Leela, and Bender log in with `auth_service=ldap`. After link, `ship_crew` is a Mattermost group (`source=ldap`, `allow_reference=true`) with those three members, and it is linked to team `planet-express` with `auto_add`.

`@ship_crew` in `bridge` incremented `mentioncount` for fry, leela, and bender. The sender's count stayed 0. That is the server treating the token as a group mention. Docs used: https://docs.mattermost.com/administration-guide/onboard/ad-ldap-groups-synchronization.html

## Incoming webhook

`scripts/workspace.py` creates an incoming webhook on `alerts` and posts:

```bash
curl -sS -X POST "http://127.0.0.1:8065/hooks/h69ckfc9pff7jnyr7fmqrpar6e" \
  -H 'Content-Type: application/json' \
  -d '{"text":"Incoming webhook check: Planet Express alerts channel is live."}'
```

The hook id is stable for this database. A new bootstrap generates a new one; `workspace.py` prints the URL. The post is visible in `alerts`.

## Total Sessions

The SQL, the API name, and the live check are in [docs/total-sessions.md](docs/total-sessions.md). Short version: `SELECT COUNT(*) FROM Sessions WHERE ExpiresAt > <unix millis>`. The panel reads `GET /api/v4/analytics/old?name=extra_counts`, row `session_count`. The API value and that SQL matched on the first check (13). Later API reads were 19, then 23.

## Layout

```
deploy/data-plane.yaml    Postgres, MinIO, OpenLDAP
deploy/mattermost.yaml    Operator secret and Mattermost CR
scripts/bootstrap.sh      Helm, image pulls, apply
scripts/workspace.py      Admin, team, LDAP link, webhook, mention
docs/total-sessions.md    Site Statistics investigation
secrets/                  gitignored admin env and evidence
```
