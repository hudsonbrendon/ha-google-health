# Google Health API v4 — notas de engenharia reversa

Fontes: discovery document `https://health.googleapis.com/$discovery/rest?version=v4`
(revisão **20261114**), código da lib `google-health-api==0.9.0` usada pela
integração do core (HA 2026.11) e testes com uma conta real (15/11/2026).

## Autenticação

OAuth2 do Google (`accounts.google.com/o/oauth2/v2/auth` → `oauth2.googleapis.com/token`)
com credenciais próprias (Configurações › Credenciais de aplicativo). Escopos:

| Escopo (`googlehealth.*`) | Libera |
|---|---|
| `activity_and_fitness.readonly` | passos, distância, calorias, andares, altitude, minutos ativos/AZM, sedentarismo, zonas de FC, exercícios, FC, VO2 máx |
| `health_metrics_and_measurements.readonly` | peso, altura, gordura, temperatura, glicose, SpO2, VFC, FC repouso, respiração |
| `sleep.readonly` | sono |
| `nutrition.readonly` | água, diário alimentar, alimentos |
| `profile.readonly` / `settings.readonly` | perfil, identidade, configurações, aparelhos |
| `ecg.readonly` | eletrocardiograma |
| `irn.readonly` | notificação de ritmo irregular + `irnProfile` |
| `*.writeonly` | criação de data points (atividade, medições, nutrição, sono, perfil, configurações) |

A integração do core pede só os 7 primeiros. Esta pede também ECG, IRN e escrita
(atividade/medições/nutrição); se a conta ainda não deu, abre um aviso em Reparos.

## Endpoints (`/v4/users/me/...`)

| Método | Caminho | Uso |
|---|---|---|
| GET | `profile`, `settings`, `identity`, `irnProfile` | perfil (idade, membro desde, passada), unidades/fuso, `healthUserId` + `legacyUserId` (Fitbit) |
| GET | `pairedDevices` | rastreadores/balanças 1P (bateria, última sync, recursos) |
| GET | `dataTypes/{t}/dataPoints?pageSize&filter&pageToken` | lista, **mais novo primeiro** (máx 10000; sono/exercício máx 25) |
| POST | `dataTypes/{t}/dataPoints:dailyRollUp` | `{range:{start,end:CivilDateTime}, windowSizeDays}` → um ponto por dia civil (dias vazios omitidos, ordem desc) |
| POST | `dataTypes/{t}/dataPoints:rollUp` | idem por janela física (`windowSize: "3600s"`) |
| GET | `dataTypes/{t}/dataPoints:reconcile` | funde fontes (`dataSourceFamily`: all-sources, google-wearables, google-sources, self-sources) |
| POST/PATCH | `dataTypes/{t}/dataPoints[/{id}]` | escrita (retorna `Operation`; origem gravada = `GOOGLE_WEB_API` + client id) |
| POST | `dataTypes/{t}/dataPoints:batchDelete` `{names:[...]}` | apaga (o `DELETE` de um ponto só dá 404 — validado 15/11) |
| GET | `dataTypes/exercise/dataPoints/{id}:exportExerciseTcx?alt=media` | TCX do treino |
| * | `projects/{p}/subscribers[/subscriptions]` | webhooks (push) — exige registro no projeto Cloud |

### Filtro (AIP-160), campo depende do tipo

- intervalo: `{tipo}.interval.start_time` (RFC 3339) — steps, distance, floors…
- civil: `{tipo}.interval.civil_start_time` (`YYYY-MM-DD[THH:mm:ss]`) — exercise, hydration_log, nutrition_log, irn
- amostra: `{tipo}.sample_time.physical_time` — heart_rate, weight, height, body_fat, spo2, hrv…
- diário: `{tipo}.date` (`YYYY-MM-DD`) — daily_*
- **sono**: só `sleep.interval.end_time` / `civil_end_time` (start_time dá `INVALID_DATA_POINT_FILTER_DATA_TYPE_MEMBER`)
- **ECG**: só `>=` no start_time

Nomes no caminho usam hífen (`daily-resting-heart-rate`); no filtro, sublinhado.

## Tipos de dado e o que cada endpoint aceita (testado)

| Tipo | list | dailyRollUp |
|---|---|---|
| steps, distance, active-energy-burned, altitude, heart-rate, weight, body-fat, hydration-log, nutrition-log, core-body-temperature, blood-glucose, run-vo2-max, swim-lengths-data, active-minutes, active-zone-minutes, sedentary-period | ✓ | ✓ |
| time-in-heart-rate-zone | ✗ (500, bug do servidor) | ✓ |
| total-calories, floors, calories-in-heart-rate-zone | ✗ (400) | ✓ |
| basal-energy-burned, activity-level | ✓ | ✗ |
| sleep, exercise, height, food, food-measurement-unit, heart-rate-variability, oxygen-saturation, respiratory-rate-sleep-summary, vo2-max | ✓ | — |
| daily-resting-heart-rate, daily-heart-rate-variability, daily-heart-rate-zones, daily-oxygen-saturation, daily-respiratory-rate, daily-sleep-temperature-derivations, daily-vo2-max | ✓ | — |
| electrocardiogram, irregular-rhythm-notification | ✓ (escopo próprio) | — |
| menstrual-period, moods, ovulation-test, symptoms | ✗ só escrita | — |

Valores int64 vêm como **string** (`"countSum": "111"`), durações como `"1828.36s"`.

### Formatos principais

- rollup: `{civilStartTime:{date:{year,month,day},time:{}}, civilEndTime, steps:{countSum}}`;
  `distance.millimetersSum`, `*Energy*.kcalSum`, `heartRate.{beatsPerMinuteAvg,Min,Max}`,
  `activeMinutes.activeMinutesRollupByActivityLevel[{activityLevel,activeMinutesSum}]`,
  `activeZoneMinutes.{sumInFatBurnHeartZone,sumInCardioHeartZone,sumInPeakHeartZone}`,
  `timeInHeartRateZone.timeInHeartRateZones[{heartRateZone,duration}]`,
  `hydrationLog.amountConsumed.millilitersSum`,
  `nutritionLog.{energy.kcalSum,totalCarbohydrate.gramsSum,totalFat.gramsSum,nutrients[{nutrient,quantity.gramsSum}]}`.
- sono: `interval`, `type` (STAGES/CLASSIC), `stages[]`, `summary.{minutesAsleep,minutesAwake,
  minutesInSleepPeriod,minutesToFallAsleep,minutesAfterWakeUp,stagesSummary[{type,minutes,count}]}`,
  `metadata.{mainSleep,nap,stagesStatus}`.
- exercício: `exerciseType` (≈190 enums), `displayName`, `activeDuration`, `exerciseEvents[]`,
  `metricsSummary.{caloriesKcal,averageHeartRateBeatsPerMinute,distanceMillimeters,steps,
  activeZoneMinutes,averagePaceSecondsPerMeter,elevationGainMillimeters,runVo2Max,
  heartRateZoneDurations,mobilityMetrics}`, `splitSummaries[]`.
- `dataSource.{platform (FITBIT|HEALTH_KIT|HEALTH_CONNECT|…), device.displayName, application.packageName, recordingMethod}`.

## Escrita (validada 15/11/2026)

`registrar_agua` com 1 mL criou o ponto, o sensor leu 0,001 L no mesmo minuto e o ponto foi
apagado com `batchDelete`. Escopos extras liberados via Reconfigurar; `include_granted_scopes`
NÃO pode ser usado (o client OAuth também tem Drive/YouTube e o Google recusa a mistura).

## Observações da conta testada

Todos os dados vêm de **uma única sincronização do Apple Health (HEALTH_KIT) em
30/07/2026** (dia do cadastro). Nada novo desde então: o app Google Health no
iPhone não está sincronizando o HealthKit em segundo plano. Só `daily-heart-rate-zones`
(derivado pela própria Fitbit) segue atualizando. Nenhum aparelho 1P pareado.
O sensor **Último dado recebido** (+ atributo `dias_sem_dados`) deixa isso visível.
