<p align="center">
  <img src="custom_components/google_health/brand/logo@2x.png" alt="Google Health" height="128">
</p>

# Google Health — Home Assistant (completa)

[![Tests](https://github.com/hudsonbrendon/ha-google-health/actions/workflows/tests.yml/badge.svg)](https://github.com/hudsonbrendon/ha-google-health/actions/workflows/tests.yml)
[![Hassfest](https://github.com/hudsonbrendon/ha-google-health/actions/workflows/hassfest.yml/badge.svg)](https://github.com/hudsonbrendon/ha-google-health/actions/workflows/hassfest.yml)
[![HACS](https://github.com/hudsonbrendon/ha-google-health/actions/workflows/validate.yml/badge.svg)](https://github.com/hudsonbrendon/ha-google-health/actions/workflows/validate.yml)
[![Release](https://img.shields.io/github/v/release/hudsonbrendon/ha-google-health?sort=semver)](https://github.com/hudsonbrendon/ha-google-health/releases)
[![Downloads](https://img.shields.io/github/downloads/hudsonbrendon/ha-google-health/total)](https://github.com/hudsonbrendon/ha-google-health/releases)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.10.0%2B-18BCF2?logo=homeassistant&logoColor=white)](https://www.home-assistant.io/)
[![License](https://img.shields.io/github/license/hudsonbrendon/ha-google-health)](LICENSE)

Substitui a integração **Google Health** do core (mesmo domínio `google_health`),
que só traz 15 sensores básicos, por uma versão que usa praticamente toda a
**Google Health API v4**: ~80 sensores em português, 2 calendários, serviços de
consulta livre e de registro (peso, água, refeição, exercício).

Ao instalar, ela **adota** a config entry, as credenciais OAuth e as entidades
que já existiam (mesmos `unique_id`), então nada precisa ser refeito.

> Não oficial, sem afiliação com o Google. Detalhes da API em
> [REVERSE_ENGINEERING.md](REVERSE_ENGINEERING.md).

## Instalação

[![Abrir no HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=hudsonbrendon&repository=ha-google-health&category=integration)
[![Adicionar integração](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=google_health)

1. Copie `custom_components/google_health` para `/config/custom_components/`
   (ou adicione o repositório no Marketplace/HACS como integração).
2. Reinicie o Home Assistant.
3. Se ainda não tinha a integração: Configurações › Dispositivos e serviços ›
   Adicionar › **Google Health**, com credenciais OAuth de um projeto do Google
   Cloud com a **Google Health API** ativada (tipo "Aplicativo da Web").
4. Para ECG, alertas de ritmo irregular, GPS dos treinos (TCX) e serviços de registro, aceite as
   permissões extras: Google Health › ⋮ › **Reconfigurar**. Enquanto não aceitar,
   aparece um aviso em Reparos e o resto funciona normalmente.

## Dispositivos e entidades

Uma conta vira sete dispositivos. Medições pontuais trazem `medido_em`
(dd/mm/aaaa HH:MM) e `fonte` (ex.: `Apple Watch (HEALTH_KIT)`) nos atributos.

### Google Health Atividade (hoje, fuso do HA)
Passos (atributo com os últimos 7 dias) · Passos ontem · Média de passos (7 dias) ·
Distância · Calorias ativas · Calorias totais · Calorias basais · Andares · Elevação ·
Minutos ativos (por intensidade) · Minutos em zona ativa (queima de gordura/cardio/pico) ·
Tempo sedentário · Tempo em zonas de FC · Calorias em zonas de FC

### Google Health Coração
Frequência cardíaca (última) · FC média hoje (mín/máx) · FC em repouso ·
Variabilidade da FC (diária; RMSSD no sono profundo, entropia) · VFC última medição ·
SpO2 (diária, faixa) · SpO2 última · Frequência respiratória · VO2 máx (nível de
condicionamento) · VO2 máx de corrida · Zonas de FC · Último ECG* · Alerta de ritmo irregular*

### Google Health Corpo
Peso · Altura · IMC · Gordura corporal · Temperatura corporal · Variação da
temperatura da pele (sono) · Glicose

### Google Health Sono (última noite principal; cochilos ignorados)
Tempo dormindo · Tempo na cama · Tempo acordado · Tempo para adormecer ·
Tempo na cama após acordar · Sono profundo / leve / REM · Despertares ·
Eficiência do sono · Início / Fim do sono · Média de sono (7 noites) ·
Respiração durante o sono · 📅 **Sono** (cada noite com fases e eficiência)

### Google Health Nutrição (hoje)
Água ingerida · Calorias consumidas · Carboidratos · Gorduras · Proteínas ·
Fibras · Açúcar · Sódio · Cafeína · Última refeição

### Google Health Exercícios
Último exercício (tipo em pt + duração, calorias, FC, distância, passos, ritmo,
elevação, GPS…) · Início / Duração / Calorias / FC média do último exercício ·
Exercícios, minutos e calorias nos últimos 7 dias · 📅 **Exercícios**

### Google Health Conta
Idade (perfil, passadas, unidades, fuso, IDs) · Membro desde · Aparelhos pareados ·
**Último dado recebido** (com `dias_sem_dados` — mostra se o app parou de sincronizar;
no iPhone, confira Ajustes › Saúde › Acesso a Dados e Dispositivos › Google Health).
**Última notificação em tempo real** (webhook). Cada rastreador/balança Fitbit ou Pixel Watch pareado vira um dispositivo com
**Bateria** e **Última sincronização**.

\* só com a permissão de ECG/IRN.

## Serviços

| Serviço | O que faz |
|---|---|
| `google_health.buscar_dados` | Devolve (response) os data points crus de **qualquer** tipo num intervalo, ou o agregado diário. Ex.: `tipo: heart-rate, inicio: "2026-11-14 00:00"` |
| `google_health.registrar_peso` | Grava peso (e gordura opcional). Não duplica se já houver pesagem igual (±0,3 kg) em ±15 min |
| `google_health.registrar_agua` | Grava água (mL) |
| `google_health.registrar_refeicao` | Grava alimento com kcal, carboidratos, gorduras, proteínas e refeição |
| `google_health.registrar_exercicio` | Grava sessão de exercício (tipo, duração, kcal, distância). Não duplica se o relógio já gravou o treino |
| `google_health.exportar_treino_tcx` | Salva o TCX (percurso/GPS) de um exercício em `/media/google_health/` |
| `google_health.importar_historico` | Importa/atualiza o histórico nas estatísticas (roda sozinho de hora em hora) |
| `google_health.info_notificacoes` | URL e segredo do webhook, para registrar o assinante (tempo real) |

Os serviços de gravação respondem `{gravado: true}` ou `{gravado: false, motivo: ...}`.
Em [`examples/automacoes.yaml`](examples/automacoes.yaml) há automações prontas:
balança → peso, treino do openGym → exercício, aviso de sincronização parada e
meta de passos.

## Histórico (gráficos de meses)

A integração grava estatísticas de longo prazo `google_health:*` — passos,
distância, calorias ativas, andares e frequência cardíaca **por hora**, e peso,
FC em repouso, variabilidade da FC, respiração, sono e gordura por medição. Na
primeira carga busca até 1 ano; depois atualiza de hora em hora. Use em cards
**Estatística/Gráfico de estatísticas** (`statistics-graph`) com
`entities: [google_health:passos]`. O painel de exemplo
[`examples/dashboard-saude.json`](examples/dashboard-saude.json) usa todas.

## Tempo real (webhook)

Por padrão a integração consulta a API a cada 15/30 min. Para receber dados
**no mesmo segundo** em que o relógio/celular sincroniza, registre um assinante
no seu projeto do Google Cloud apontando para o webhook da integração (uma vez):

1. Pegue a URL e o segredo: **Ferramentas de desenvolvedor › Ações ›
   `google_health.info_notificacoes`**. Se vier só o caminho, prefixe com o
   endereço HTTPS público do seu HA (Nabu Casa, Cloudflare Tunnel…).
2. Com o [gcloud](https://cloud.google.com/sdk) logado na conta dona do projeto:

```bash
curl -X POST "https://health.googleapis.com/v4/projects/<NÚMERO_DO_PROJETO>/subscribers?subscriberId=home-assistant" \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "x-goog-user-project: <ID_DO_PROJETO>" -H "Content-Type: application/json" \
  -d '{"endpointUri": "<URL>", "endpointAuthorization": {"secret": "<SEGREDO>"},
       "subscriberConfigs": [{"subscriptionCreatePolicy": "AUTOMATIC",
         "dataTypes": ["steps","distance","floors","heart-rate","daily-resting-heart-rate",
           "heart-rate-variability","daily-heart-rate-variability","sleep","exercise",
           "weight","body-fat","hydration-log","nutrition-log","daily-respiratory-rate"]}]}'
```

O Google verifica o endpoint (201 com o segredo, 401 sem) antes de aceitar. Cada
notificação dispara o evento `google_health_notificacao` (tipo de dado, operação,
intervalo) e atualiza os sensores na hora; o sensor **Última notificação em tempo
real** mostra que está chegando. Doc oficial:
<https://developers.google.com/health/webhooks>.

## Atualização

| Grupo | Intervalo |
|---|---|
| Atividade, coração, nutrição | 15 min (ou na hora, com webhook) |
| Corpo, sono, exercícios | 30 min (ou na hora, com webhook) |
| Conta e aparelhos | 6 h |
| Histórico (estatísticas) | 1 h |

Os calendários consultam a API sob demanda, então mostram todo o histórico.

## Testes

```bash
uv run --with pytest pytest tests/test_parse.py          # parsers, sem HA
pytest tests                                            # com pytest-homeassistant-custom-component
```
