# Novo Sistema DevGis

Aplicação Flask com autenticação, painel administrativo unificado ao layout do site, módulo público de boas-vindas e módulo SIG Web para upload/gestão de GeoJSONs e visualização em mapa.

## Stack
- Python 3.11 (Docker)
- Flask 3
- Flask-Login, Flask-WTF, Flask-Admin, Flask-Migrate, Flask-Bcrypt
- SQLAlchemy 2 + Postgres (Docker)
- WTForms 2.3.3 (compatibilidade com Flask-Admin)
- Leaflet.js para mapa
- Docker Compose

## Executando com Docker
```bash
# build e subir
docker compose up -d --build

# logs (opcional)
docker compose logs -f web
```

App: http://localhost:5000/

## Acesso
- Página de boas-vindas (pública): `/`
- Login/Logout/Registro: `/auth/login`, `/auth/logout`, `/auth/register`
- Admin (privado, papel admin): `/admin/`
  - Usa o mesmo layout do site
  - Módulos: Usuários, Papéis, Vínculos, Logs, GeoJSONs

## Criando Superusuário (admin)
```bash
docker compose exec web python manage.py reset-and-create-admin \
  --name admin \
  --email admin@admin.local \
  --password admin123
```
Credenciais: `admin` / `admin123` (também vale o e-mail)

## Módulo SIG Web
- Upload e gerenciamento de GeoJSON por usuário autenticado
- Visualização em mapa (Leaflet) somente dos arquivos do próprio usuário
- URLs:
  - Gerenciamento: `/sig/files`
  - Mapa (tela cheia): `/sig/map`
  - API (GeoJSONs do usuário logado): `/sig/api/my-geojsons`
- Carregar exemplos:
  - Botão "Carregar exemplos" em `/sig/files` (insere 3 GeoJSONs de `examples/` para o usuário atual)

### Restrições de Acesso
- Usuário enxerga e manipula apenas seus próprios arquivos.
- Admin panel também lista `GeoJSONFile`, mas pode ser limitado posteriormente por papel.

## Estrutura de Permissões
- Módulo de boas-vindas: público (`/`)
- Admin: login + papel `admin`
- SIG Web: requer login

## Desenvolvimento
### Estrutura de diretórios
- `app/`
  - `__init__.py`: fábrica do app, login, admin, blueprints
  - `models.py`: `User`, `Role`, `UserRole`, `AccessLog`, `GeoJSONFile`
  - `views.py`: rota de boas-vindas (pública)
  - `auth.py`: login/logout/registro
  - `sig.py`: upload/gestão de GeoJSON e mapa
  - `templates/`
    - `base.html`: layout principal
    - `admin/`: templates do Admin
    - `auth/`: login/registro
    - `sig/`: `files.html` e `map.html`
  - `static/css/style.css`: estilos
- `examples/`: `exemplo1.geojson`, `exemplo2.geojson`, `exemplo3.geojson`
- `manage.py`: utilitários (reset e criar admin)
- `docker-compose.yml`, `Dockerfile`, `requirements.txt`, `wsgi.py`

## Observações
- Se `/admin/.../new` apresentar erro de formulário, verifique a versão do WTForms (está fixada em 2.3.3 para compatibilidade com Flask-Admin 1.6.1).
- Compose: a chave `version` é obsoleta e foi mantida apenas por compatibilidade. Pode ser removida futuramente.

## Git
- Branch principal: `main`
- Remote: `origin` (GitHub)

```bash
# commit e push
git add -A
git commit -m "feat(sig): upload/gestão GeoJSON e mapa; README"
git push
```
