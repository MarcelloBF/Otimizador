# Otimizador de PC

Aplicativo para Windows 10/11 que lê as especificações do computador, diagnostica o que está limitando o desempenho e aplica otimizações **reversíveis**.

## Como abrir

- **Executável pronto:** `dist\Otimizador.exe` (pede administrador ao abrir).
- **Pelo código:** dê dois cliques em `Otimizador.bat`, ou rode `.venv\Scripts\python.exe main.py`.
- **Gerar o .exe de novo:** `powershell -ExecutionPolicy Bypass -File build.ps1`

## O que ele faz

| Página | Função |
|---|---|
| **Painel** | Nota de saúde (0–100), resumo do PC, CPU/RAM/disco/rede em tempo real, programas que mais usam RAM e botão **Otimizar agora** (1 clique). |
| **Especificações** | Windows, processador, placas de vídeo (VRAM real e driver), cada pente de RAM (velocidade nominal × configurada), discos (SSD/HDD, NVMe/SATA, saúde, temperatura e desgaste quando aberto como admin), volumes, placa-mãe/BIOS, Secure Boot, TPM, VBS, rede, monitores, energia. Exporta relatório `.txt`. |
| **Diagnóstico** | Mais de 30 regras: Windows em HD, pouca RAM, single-channel, XMP/EXPO desligado, disco cheio ou com defeito, driver de vídeo antigo, monitor a 60 Hz ou ligado na placa-mãe, cabo de rede negociando 100 Mbps, plano de energia, Game DVR, HAGS, VBS, muitos programas na inicialização, lixo acumulado, PC sem reiniciar etc. Classifica o PC (Entrada / Intermediário / Alto desempenho) e indica o **melhor perfil** para ele. |
| **Otimizações** | 27 ajustes em 6 categorias, com perfis *Recomendado*, *Gamer*, *Notebook* e *Máximo*. Cada item mostra risco, ganho real esperado e se precisa reiniciar. |
| **Limpeza** | Temporários, cache do Windows Update, Otimização de Entrega, relatórios de erro, miniaturas, cache de navegadores (sem apagar senhas/histórico), cache de shaders, logs antigos e Lixeira. |
| **Inicialização** | Liga/desliga programas da inicialização (mesmo mecanismo do Gerenciador de Tarefas), com sugestão para cada um (manter / pode desativar). |
| **Ferramentas** | Ponto de restauração, SFC, DISM, limpeza do WinSxS, TRIM/desfragmentação, chkdsk, flush DNS, reset de rede, relatórios de bateria e energia, atalhos do Windows. |
| **Backup e restauração** | Lista tudo o que o app alterou e desfaz item por item ou tudo de uma vez. |

## Segurança

- Antes de qualquer alteração o valor original é salvo em `%LOCALAPPDATA%\Otimizador\backup.json`; desfazer restaura exatamente o estado anterior (inclusive apagando valores que não existiam).
- Opção de criar um ponto de restauração do Windows antes de aplicar.
- Itens de risco alto (como desligar a Integridade de Memória/VBS) **nunca** são marcados automaticamente por nenhum perfil.
- Fica de fora o que a pesquisa mostrou ser placebo ou perigoso: desligar o Defender ou o Windows Update, remover o Edge, "limpador de registro", limpar Prefetch, ajustes de TCP sem efeito no Windows moderno.

## Testes

```powershell
.venv\Scripts\python.exe tests\test_core.py
```
