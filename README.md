# Radar GIS Local IPMET

Visualizador do Radar GIS Local do IPMET, com mapa restrito ao estado de São Paulo, histórico de capturas WMS, alertas TITAN e legenda dBZ oficial.

## Publicação

O workflow em `.github/workflows/update-ipmet-radar.yml` coleta os dados oficiais e publica o site no GitHub Pages. Ele roda a cada 10 minutos e também após alterações na branch `main`.

O primeiro quadro aparece assim que a primeira execução do workflow termina. A animação fica disponível quando houver pelo menos duas capturas diferentes.

## Google Sites

No Google Sites, escolha **Inserir → Incorporar → Código de incorporação** e use o conteúdo de `google-sites-embed.html`.