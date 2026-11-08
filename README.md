# Nova Agenda 2027 — Enfermagem Oncológica (INCA HC II)

Sistema web de **agendamento de quimioterapia, consultas de enfermagem e teleconsultas**, com controle de
ocupação das poltronas (Boxes), mural diário para impressão, cadastro de pacientes, registro de
intercorrências, estatísticas diárias, mapa de calor de cadeiras ociosas e dashboards gerenciais.

A versão 2.0 **substitui a planilha Google Sheets por um banco de dados PostgreSQL local**. Ela roda numa VM
Linux da Intranet, empacotada em contêineres Docker. **Nenhum dado sai da rede do hospital.** A única
exceção é a consulta opcional de CEP, que envia apenas o CEP digitado, e pode ser desligada.

> Este documento é dividido em duas partes:
> **Parte A — para a equipe de TI** (instalação, operação, backup, segurança) e
> **Parte B — para os usuários** (como usar cada tela).

---

## Sumário

**Parte A — TI**
1. [Visão geral da arquitetura](#1-visão-geral-da-arquitetura)
2. [Requisitos da VM](#2-requisitos-da-vm)
3. [Instalar o Docker no Linux](#3-instalar-o-docker-no-linux)
4. [Instalação da Nova Agenda](#4-instalação-da-nova-agenda)
5. [Certificado HTTPS](#5-certificado-https)
6. [Backup e restauração](#6-backup-e-restauração)
7. [Importar os dados da planilha antiga](#7-importar-os-dados-da-planilha-antiga)
8. [Operação do dia a dia](#8-operação-do-dia-a-dia)
9. [Configurações (.env)](#9-configurações-env)
10. [Segurança e LGPD](#10-segurança-e-lgpd)
11. [Testes automatizados](#11-testes-automatizados)
12. [Atualização de versão](#12-atualização-de-versão)
13. [Solução de problemas](#13-solução-de-problemas)
14. [Estrutura do projeto](#14-estrutura-do-projeto)

**Parte B — Usuários**

15. [Perfis de acesso](#15-perfis-de-acesso)
16. [Primeiro acesso](#16-primeiro-acesso)
17. [Uso das telas](#17-uso-das-telas)
18. [Regras de agendamento](#18-regras-de-agendamento)

---

# PARTE A — EQUIPE DE TI

## 1. Visão geral da arquitetura

```
 Navegador (PC / tablet / celular na Intranet)
            │  HTTPS 443  (HTTP 80 apenas redireciona)
            ▼
 ┌──────────────────┐   rede "frontal"   ┌──────────────────────┐
 │ nginx            │ ─────────────────► │ app (FastAPI/Python) │ ──► ViaCEP (opcional, só o CEP)
 │ TLS, limites,    │                    │ usuário sem root,    │
 │ cabeçalhos       │                    │ disco somente leitura│
 └──────────────────┘                    └──────────┬───────────┘
                                                    │ rede "interna" (sem acesso externo)
                                         ┌──────────▼───────────┐     ┌───────────────────┐
                                         │ db (PostgreSQL 16)   │ ◄── │ backup (pg_dump)  │
                                         │ volume db_data       │     │ todo dia 00:00    │
                                         └──────────────────────┘     └─────────┬─────────┘
                                                                                ▼
                                                                        ./backups/*.dump
```

| Contêiner | Função | Portas |
|---|---|---|
| `nginx`  | Terminação HTTPS, redireciona HTTP→HTTPS, limita tentativas de login, cabeçalhos de segurança | **443** e 80 publicadas na VM |
| `app`    | Aplicação web e API (FastAPI + Uvicorn, 2 processos) | nenhuma publicada |
| `db`     | Banco PostgreSQL 16, autenticação SCRAM-SHA-256 | nenhuma publicada (rede interna) |
| `backup` | `pg_dump` diário com verificação de integridade e limpeza das cópias antigas | nenhuma |

## 2. Requisitos da VM

- Linux 64 bits: Ubuntu Server 22.04/24.04 LTS, Debian 12 ou Rocky/AlmaLinux 9.
- 2 vCPU, 2 GB de RAM (4 GB recomendado) e 20 GB de disco, mais o espaço dos backups.
- IP fixo na Intranet e, de preferência, um nome DNS interno (ex.: `agenda.hospital.local`).
- Saída para a internet **opcional**. É necessária apenas na instalação, para baixar as imagens Docker, e
  para a busca de CEP. Sem internet, o endereço é digitado à mão.
- Firewall liberando **TCP 443** (e 80, se quiser o redirecionamento) **somente para a rede interna**.

## 3. Instalar o Docker no Linux

**Ubuntu / Debian** (repositório oficial da Docker):

```bash
sudo apt-get update && sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/$(. /etc/os-release; echo "$ID")/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$(. /etc/os-release; echo "$ID") $(. /etc/os-release; echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo systemctl enable --now docker
```

**Rocky / AlmaLinux / RHEL:**

```bash
sudo dnf -y install dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo
sudo dnf -y install docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo systemctl enable --now docker
```

Para conferir: `docker compose version` deve mostrar a versão 2.x.

## 4. Instalação da Nova Agenda

1. Copie a pasta `nova-agenda-2027` para a VM, por exemplo em `/opt/nova-agenda-2027`.
2. Rode o instalador:

```bash
cd /opt/nova-agenda-2027
sudo ./scripts/instalar.sh
```

O instalador:

- cria o `.env` a partir do `.env.example` e pergunta o nome e o IP do servidor;
- gera uma **senha aleatória de 48 caracteres** para o banco em `secrets/db_password.txt`. Ela nunca é
  exibida nem fica em variável de ambiente;
- constrói as imagens e sobe os 4 contêineres;
- cria o **primeiro administrador** e mostra a **senha temporária** dele na tela. Anote essa senha: ela
  será trocada obrigatoriamente no primeiro acesso.

3. Acesse `https://agenda.hospital.local` (ou `https://IP-DA-VM`).
4. Entre com o administrador e cadastre os usuários em **Usuários e permissões**.

> Precisa de outro administrador mais tarde? Rode `./scripts/criar-admin.sh login "Nome Completo"`.

## 5. Certificado HTTPS

- **Com certificado institucional** (recomendado): copie os arquivos para `nginx/certs/servidor.crt` (com a
  cadeia intermediária) e `nginx/certs/servidor.key` e reinicie com `docker compose restart nginx`.
- **Sem certificado:** na primeira execução é gerado um certificado **autoassinado** (RSA 3072, 825 dias),
  válido para `SERVIDOR_NOME` e `SERVIDOR_IP`. Os navegadores mostram um aviso até a TI distribuir o
  `nginx/certs/servidor.crt` como confiável nas estações, por GPO ou MDM. Para gerar de novo, apague os dois
  arquivos e reinicie o nginx.

## 6. Backup e restauração

- **Automático:** todo dia às **00:00** (fuso `America/Sao_Paulo`), o contêiner `backup` gera
  `backups/nova_agenda_AAAA-MM-DD_HHMM.dump` no formato do `pg_dump`, com compressão. Ele também cria o
  `.sha256` de cada arquivo e confere se o arquivo é legível (`pg_restore --list`).
- **Retenção:** as cópias com mais de `BACKUP_RETENCAO_DIAS` dias (padrão **30**) são apagadas.
- **Horário:** altere `BACKUP_CRON` no `.env` (formato cron) e rode `docker compose up -d backup`.
- **Backup manual imediato:** `./scripts/backup-agora.sh`
- **Restaurar:** `./scripts/restaurar-backup.sh backups/nova_agenda_2027-03-10_0000.dump`. O script confere
  o checksum, pede confirmação, faz um backup de segurança do estado atual e só então restaura.
- ⚠️ **Copie a pasta `backups/` para fora da VM** (servidor de arquivos ou fita) conforme a política do hospital.
  Os arquivos contêm dados de saúde: guarde-os em local com acesso restrito e, de preferência, criptografado.
- O volume do banco (`db_data`) fica no disco da VM. Recomenda-se **criptografia de disco** (LUKS ou o recurso
  equivalente do hipervisor) e o snapshot da VM como segunda camada de proteção.

## 7. Importar os dados da planilha antiga

Use esta seção se quiser trazer os dados que estavam no Google Sheets "Nova Agenda 2027".

1. No Google Sheets: **Arquivo → Fazer download → Microsoft Excel (.xlsx)**.
2. Copie o arquivo para a pasta `importacao/` da VM.
3. **Simule** a importação. Nada é gravado, e o relatório mostra apenas contagens e números de linha:

```bash
./scripts/importar-planilha.sh importacao/Nova_Agenda_2027.xlsx
```

4. Se o relatório estiver correto, grave os dados:

```bash
./scripts/importar-planilha.sh importacao/Nova_Agenda_2027.xlsx --gravar
```

5. **Apague o .xlsx** da pasta `importacao/`, porque ele contém dados pessoais.

O que é importado:

| Aba da planilha | Destino | Observações |
|---|---|---|
| Pacientes | Pacientes | CPF repetido é ignorado. CPF inválido ou vazio vira "cadastro incompleto" |
| AGENDA 2027 / CONSULTA DE ENFERMAGEM / TELECONSULTA | Agendamentos | Vínculo pelo nome do paciente. Nome ausente da aba Pacientes gera um cadastro incompleto |
| Protocolos | Protocolos | Só os que ainda não existem |
| INTERCORRÊNCIAS | Catálogo (coluna A) e registros (colunas C a I) | |
| Estatística Auditoria Clínica / Estatísca agendamento | Estatísticas diárias | Uma linha por data |
| Enfermeiros | Usuários (perfil ENFERMEIRO) | **A coluna SENHA nunca é importada.** Os usuários entram sem senha; o admin usa "Redefinir senha" em cada um |

A importação pode ser repetida: protocolos, catálogos e estatísticas não são duplicados. Pacientes e
agendamentos, porém, **seriam duplicados**. Importe esses dados apenas uma vez, num banco recém-instalado.

## 8. Operação do dia a dia

| Tarefa | Comando (na pasta do sistema) |
|---|---|
| Ver estado dos serviços | `docker compose ps` |
| Ver logs da aplicação | `docker compose logs -f app` |
| Ver logs do backup | `docker compose logs backup` |
| Parar tudo | `docker compose down` (os dados continuam no volume) |
| Iniciar tudo | `docker compose up -d` |
| Reiniciar só a aplicação | `docker compose restart app` |

Os contêineres têm `restart: unless-stopped`: voltam sozinhos quando a VM reinicia.
Os logs do Docker são rotacionados (5 arquivos de 10 MB por serviço).

> **Nunca** rode `docker compose down -v`: o `-v` apaga o volume do banco de dados.

## 9. Configurações (.env)

| Variável | Padrão | Descrição |
|---|---|---|
| `SERVIDOR_NOME` / `SERVIDOR_IP` | `agenda.local` / vazio | Nome e IP usados no certificado HTTPS |
| `HTTPS_PORTA` / `HTTP_PORTA` | 443 / 80 | Portas publicadas na VM |
| `TZ` | `America/Sao_Paulo` | Fuso horário |
| `BACKUP_CRON` | `0 0 * * *` | Horário do backup (todo dia às 00:00) |
| `BACKUP_RETENCAO_DIAS` | 30 | Dias de cópias mantidas |
| `SESSAO_INATIVIDADE_MIN` | 30 | Minutos sem uso até a sessão expirar |
| `SESSAO_MAXIMA_HORAS` | 12 | Duração máxima de uma sessão |
| `LOGIN_MAX_TENTATIVAS` / `LOGIN_BLOQUEIO_MIN` | 5 / 15 | Bloqueio de conta após senhas erradas |
| `CEP_ONLINE` | 1 | 0 desliga a consulta de CEP na internet |
| `QTD_POLTRONAS` / `HORAS_FUNCIONAMENTO_DIA` | 12 / 10 | Capacidade instalada (120 h/dia) |
| `NOME_INSTITUICAO` | INCA / HC II | Cabeçalho do mural e do PDF |

Depois de alterar: `docker compose up -d`.

## 10. Segurança e LGPD

### O que foi corrigido em relação à versão anterior

| Problema na versão 1 (planilha) | Correção na versão 2 |
|---|---|
| Chave privada da conta de serviço Google, `.env` e IDs das planilhas dentro do pacote | Removidos. A integração com o Google foi **excluída** (a chave antiga já foi revogada) |
| Planilha local com cerca de 850 nomes e prontuários reais | Removida. O pacote não contém nenhum dado pessoal |
| Login `admin/admin` e enfermeiro com o **CPF como senha** | Sem senha padrão. O 1º admin recebe senha aleatória e todas as senhas temporárias são trocadas no 1º acesso |
| Senhas em texto puro na planilha | Hash **Argon2id** com política mínima (10+ caracteres, letras e números, sem nome, usuário ou CPF) |
| Quase toda a API funcionava **sem login**, e a checagem de perfil deixava passar quem não estava logado | **Todas** as rotas exigem sessão, e o perfil é verificado no servidor em cada requisição |
| Chave do token escrita no código; token guardado no `localStorage` | Sessão aleatória guardada no servidor (só o hash SHA-256), em cookie `HttpOnly` + `Secure` + `SameSite=Strict` |
| Sem proteção CSRF | Token CSRF por sessão, exigido em toda operação de escrita |
| CORS aberto para qualquer site | CORS removido (só a própria origem) |
| HTML montado com dados sem escape (risco de XSS) | Escape automático de todo dado na interface, além de uma **Content-Security-Policy** estrita, sem scripts inline |
| Mensagens de erro com detalhes internos | Mensagens genéricas. O detalhe fica só no log do servidor |
| "Operador" do log informado pelo navegador | O log usa o usuário autenticado na sessão |
| Sem limite de tentativas de login | Bloqueio de conta (5 erros = 15 min), limite por IP na aplicação e no Nginx |
| HTTP sem criptografia | HTTPS obrigatório (TLS 1.2/1.3) com HSTS |
| Imagens com metadados EXIF de câmera | Imagens recodificadas sem metadados |
| Dependências com vulnerabilidades conhecidas (Starlette) | Versões fixadas e auditadas com `pip-audit`: sem vulnerabilidades conhecidas em 07/11/2026 |

### Controles em vigor

- **Autenticação e sessão:** Argon2id; verificação de senha com tempo constante (não revela se o usuário
  existe); mensagem única de erro; expiração por inatividade e duração máxima; sessões encerradas na troca de
  senha, na desativação do usuário e em "Redefinir senha"; o último administrador ativo não pode ser removido.
- **Autorização:** perfis ADMIN, ENFERMEIRO e GESTOR verificados no servidor (ver seção 15).
- **Minimização de dados (LGPD):** a busca de pacientes devolve o CPF mascarado (`***.982.247-**`) e não
  devolve telefone nem endereço. O cadastro completo só aparece ao abrir a ficha, e essa abertura fica
  registrada no log. CPF e termos de busca trafegam no corpo da requisição (POST), nunca na URL. O Nginx não
  grava a query string no log de acesso. As respostas da API têm `Cache-Control: no-store`.
- **Trilha de auditoria:** login, falhas de login, bloqueios, cadastros, alterações, encerramentos,
  exclusões, exportações de PDF/PNG e visualizações de ficha registram usuário, data e hora, IP e ID interno do
  registro. **O log nunca contém CPF, nome ou telefone.** O admin consulta tudo na tela **Log de auditoria**.
- **Contêineres:** a aplicação roda como usuário sem privilégios (UID 10001), com disco somente leitura,
  `cap_drop: ALL` e `no-new-privileges`. O banco fica numa rede Docker interna, sem porta publicada e sem saída
  para a internet. A senha do banco é um *Docker secret*, e não uma variável de ambiente.
- **Cabeçalhos:** CSP, HSTS, X-Frame-Options DENY, X-Content-Type-Options, Referrer-Policy no-referrer e
  Permissions-Policy. A documentação automática da API (`/docs`) está desligada.
- **Entradas:** validação de tamanho e formato no servidor para todos os campos (CPF com dígito verificador,
  datas, horários, e-mail, UF, CEP), consultas parametrizadas (SQLAlchemy) e escape do texto no PDF e no PNG.

### Recomendações para a TI

1. Restrinja a porta 443 à rede interna (firewall) e **não publique o sistema na internet**.
2. Use certificado institucional e distribua a CA às estações.
3. Criptografe o disco da VM e o destino das cópias de backup.
4. Faça um teste de restauração de backup a cada trimestre.
5. Revise periodicamente a tela **Usuários e permissões** (desative quem saiu do setor) e o **Log de auditoria**.
6. Mantenha a VM atualizada (`apt upgrade`/`dnf upgrade`) e reconstrua as imagens mensalmente
   (`docker compose build --pull && docker compose up -d`) para receber correções do sistema base.

## 11. Testes automatizados

A suíte tem **45 testes**:

- **Regras de negócio:** CPF único, encerramento e reativação, prontuário automático, conflito de Box pela
  duração do protocolo, falta que libera a vaga, agendamento cruzado, consultas de 1 h das 08:00 às 17:00,
  mural, intercorrências, estatísticas, dashboard, mapa de calor e painel ao vivo.
- **Segurança:** todas as rotas exigem login, mensagem de login genérica, bloqueio por tentativas, cookie
  seguro, hash Argon2id, CSRF, logout, cookie forjado, permissões de cada perfil, troca de senha obrigatória,
  política de senha, último admin, cabeçalhos, erros sem vazamento, minimização de dados, log sem dados
  pessoais, escape no PDF, expiração de sessão, usuário desativado e atualização automática que não renova a sessão.

```bash
./scripts/rodar-testes.sh
```

Os testes rodam num contêiner descartável, sem rede e com banco temporário: não tocam nos dados reais.

Auditoria de dependências (opcional, precisa de internet):

```bash
docker run --rm -v "$PWD/app:/src" python:3.12-slim sh -c "pip install -q pip-audit && pip-audit -r /src/requirements.txt"
```

## 12. Atualização de versão

```bash
./scripts/backup-agora.sh                  # 1. backup antes de tudo
# 2. substitua as pastas app/, nginx/, backup/ e scripts/ pela nova versão
#    (NÃO substitua .env, secrets/, backups/ nem nginx/certs/)
docker compose build --pull
docker compose up -d
./scripts/rodar-testes.sh
```

As tabelas novas são criadas automaticamente. Os dados existentes não são alterados.

## 13. Solução de problemas

| Sintoma | Verificação |
|---|---|
| Página não abre | `docker compose ps` (todos "running/healthy"?); firewall libera a 443? |
| Aviso de certificado | É esperado com o certificado autoassinado. Instale `nginx/certs/servidor.crt` como confiável ou use o institucional |
| "Sessão expirada" frequente | Aumente `SESSAO_INATIVIDADE_MIN` no `.env` |
| Usuário bloqueado | Admin → Usuários → **Redefinir senha** (desbloqueia e gera senha temporária) |
| Admin esqueceu a senha e não há outro admin | `./scripts/criar-admin.sh novo.admin "Nome"` |
| CEP não preenche | A VM sem internet não consulta CEP; preencha à mão ou deixe `CEP_ONLINE=0` |
| `app` não fica "healthy" | `docker compose logs app` e `docker compose logs db` |
| Backup não aparece | `docker compose logs backup`; confira `BACKUP_CRON` e o espaço em disco |

## 14. Estrutura do projeto

```
nova-agenda-2027/
├── docker-compose.yml        # pilha completa
├── .env.example              # modelo de configuração
├── scripts/                  # instalar, criar-admin, backup-agora, restaurar-backup, importar-planilha, rodar-testes
├── app/
│   ├── Dockerfile, requirements.txt
│   ├── app/
│   │   ├── main.py           # aplicação, cabeçalhos de segurança, tratamento de erros
│   │   ├── config.py, db.py, models.py, bootstrap.py, cli.py
│   │   ├── security.py       # senhas, sessões, CSRF, perfis, limitador
│   │   ├── routers/          # auth, pacientes, agenda, registros, cadastros, relatorios
│   │   ├── services/         # regras de negócio (agenda, pacientes, relatórios, exportação, endereço, auditoria)
│   │   ├── seed/             # catálogo inicial de protocolos e intercorrências (sem dados pessoais)
│   │   ├── templates/index.html
│   │   └── static/           # css, js (sem dependências externas), img
│   └── tests/                # testes funcionais e de segurança
├── nginx/                    # proxy HTTPS (certs/ recebe o certificado)
├── backup/                   # contêiner de backup
├── backups/                  # cópias diárias (gerado)
├── importacao/               # local temporário do .xlsx a importar
└── secrets/                  # senha do banco (gerada pelo instalador)
```

---

# PARTE B — USUÁRIOS

## 15. Perfis de acesso

| Tela | ADMIN | ENFERMEIRO | GESTOR |
|---|:---:|:---:|:---:|
| Painel ao vivo | ✅ | ✅ | ✅ |
| Agenda do dia (ver) | ✅ | ✅ | ✅ |
| Agendar, alterar, registrar presença/falta, excluir | ✅ | ✅ | — |
| Mural da QT (imprimir, PDF, imagem) | ✅ | ✅ | ✅ |
| Pacientes (ver) | ✅ | ✅ | ✅ |
| Pacientes (cadastrar, editar, encerrar, reativar) | ✅ | ✅ | — |
| Intercorrências (registrar) | ✅ | ✅ | ver |
| Estatísticas diárias (lançar) | ✅ | ✅ | ver |
| Mapa de calor e Dashboards | ✅ | ✅ | ✅ |
| Protocolos e catálogos (editar) | ✅ | ver | ver |
| Usuários e permissões | ✅ | — | — |
| Log de auditoria | ✅ | — | — |

## 16. Primeiro acesso

1. Abra o endereço informado pela TI no navegador do computador, tablet ou celular conectado à rede do hospital.
2. Entre com o usuário e a **senha temporária** recebidos pessoalmente do administrador.
3. O sistema pede para criar uma senha nova: mínimo de 10 caracteres, com letras e números, sem o seu nome,
   usuário ou CPF.
4. No celular, use **"Adicionar à tela inicial"** no navegador para abrir a agenda como um aplicativo.

A sessão encerra depois de 30 minutos sem uso. Em computadores compartilhados, use sempre **Sair**.

## 17. Uso das telas

**Painel ao vivo** (tela inicial, todos os perfis). Retrato simplificado do setor **agora**, que se atualiza
sozinho a cada 30 segundos:
- **Indicadores:** poltronas em uso agora (ex.: 4/12) e ocupação do dia, agendados, em atendimento,
  presentes (% de presença), aguardando chegada e faltas, atrasados e intercorrências do dia.
- **Poltronas agora:** os 12 Boxes com o estado de cada um (Livre, Em infusão com barra de progresso e horário
  de término, ou Aguardando paciente).
- **Poltronas em uso ao longo do dia:** gráfico por hora, com a hora atual destacada.
- **Em atendimento**, **Próximos a chegar** e **Atrasados**: estes últimos passaram mais de 15 minutos do
  horário sem chegada registrada.
- **⛶ Tela cheia:** para deixar o painel num monitor ou TV do setor.

Para proteger os pacientes em telas à vista de outras pessoas, os nomes aparecem abreviados (ex.: "Ana F. S.").
A atualização automática **não prolonga a sessão**: se ninguém usar o sistema por 30 minutos, a sessão expira
como em qualquer outra tela. Para um monitor fixo, aumente `SESSAO_INATIVIDADE_MIN` com cautela ou faça login
novamente quando necessário.

**Agenda do dia.** Escolha a data com as setas ou o calendário.
- A **grade** mostra os Boxes 1 a 12 e, abaixo do Box 12, as linhas **(Consulta Enf)** e **(Teleconsulta)**,
  das 08:00 às 17:00.
- Toque num horário **livre** para agendar já com o Box e a hora preenchidos. Toque num horário **ocupado**
  para ver ou alterar o agendamento.
- No celular, deslize a grade para o lado.
- Na lista **Atendimentos do dia** você marca **✓ Veio** ou **✗ Faltou**, edita ou exclui.

**Novo agendamento.**
1. Escolha a modalidade e a data.
2. Busque o paciente pelo nome, prontuário ou CPF. A busca aceita erros de digitação e ignora acentos.
3. Na quimioterapia, escolha o Box e o protocolo. O tempo estimado é preenchido sozinho.
4. A lista de horários já mostra os **horários fechados** e o motivo.
5. Se quiser, informe a enfermeira responsável, a presença, as horas reais de início e término e a
   observação. Marque **Registrar intercorrência** para lançar a ocorrência junto com o atendimento.

**Mural da QT.** É a folha do dia com todos os atendimentos das 3 modalidades. Use **Imprimir** (A4
paisagem), **PDF** ou **Imagem**.

**Pacientes.**
- Busque por nome, prontuário ou CPF. Marque "Incluir encerrados" para ver também os tratamentos encerrados.
- **Novo paciente:** o CPF é validado e checado na hora. Se já existir, o sistema avisa e oferece abrir o
  cadastro. O prontuário de 7 dígitos é gerado automaticamente se ficar em branco. O CEP preenche o endereço.
- Na ficha do paciente: **Editar**, **Encerrar tratamento** (motivo: desistência, cura ou morte) e
  **Reativar tratamento** em caso de retorno ou recidiva. A reativação usa o mesmo cadastro, sem duplicar o CPF.

**Intercorrências.** Registre data, paciente, tipo (catálogo oficial), protocolo, medida tomada e observação.
O histórico do mês fica ao lado.

**Estatísticas diárias.** Substituem as abas da planilha "Estatística Auditoria Clínica Prévia" e
"Estatística agendamento". Escolha a data e preencha os números. Se a data já tiver lançamento, os valores são
carregados para correção. A tabela do mês traz os totais.

**Mapa de calor** (todos os perfis). Calendário colorido por dia:
- 🟥 cadeiras ociosas (menos de 120 h/dia)
- 🟨 100% da capacidade
- 🟩 acima da capacidade
- ⬜ fim de semana

A tela também mostra as horas por Box, os protocolos que mais ocupam poltrona e a comparação entre o tempo
real e o estimado.

**Dashboards** (todos os perfis). Indicadores do mês, os 10 protocolos mais agendados, as pendências para o
início da QT, os pacientes com mais faltas (para busca ativa), o tempo real × estimado por protocolo
(⚡ rápido, ⏱️ no tempo, 🐢 devagar), o ritmo da equipe e as intercorrências.

**Protocolos e catálogos.** Lista de protocolos com o tempo de poltrona e o catálogo de intercorrências. O
admin inclui itens e ativa ou desativa os existentes. Para preservar o histórico, o nome de um protocolo não é
alterado: desative o antigo e cadastre um novo.

**Usuários e permissões** (admin).
- Crie usuários com o perfil adequado. O sistema gera uma **senha temporária**, que aparece só uma vez:
  entregue-a pessoalmente.
- **Redefinir senha** desbloqueia a conta e gera uma nova senha temporária.
- Desative quem deixou o setor. A desativação encerra as sessões abertas na hora.

**Log de auditoria** (admin). Consulte quem fez o quê e quando, com filtros por usuário, ação e período.

## 18. Regras de agendamento

- **CPF único:**
  - Com tratamento INICIADO, o sistema bloqueia com a mensagem *"Paciente já cadastrado com tratamento em
    andamento"*.
  - Com tratamento ENCERRADO, o sistema oferece **Reativar tratamento**.
- **Paciente encerrado não pode ser agendado:** reative o tratamento antes.
- **Bloqueio do Box pela duração do protocolo:** um protocolo de 4 h no Box 1 às 08:00 fecha o Box 1 das 08:00
  às 12:00. Um novo agendamento pode começar exatamente às 12:00.
- **Falta (Compareceu = N) libera o horário** para outro paciente.
- **Agendamento cruzado:** o mesmo paciente não pode ter dois atendimentos sobrepostos, em qualquer modalidade.
- **Consulta de Enfermagem e Teleconsulta:** 1 atendimento por hora em cada linha, com início entre 08:00 e
  17:00.
- **Horas reais de início e término**, quando informadas, substituem o horário previsto nos cálculos de
  ocupação e na análise de tempo real × estimado.
- Para o agendamento ser aceito, o protocolo e o Box precisam estar cadastrados.
