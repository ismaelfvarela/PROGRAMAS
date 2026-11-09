# Formatura 2.4: abertura e encerramento, plano

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans.

**Goal:** a colação também entrega "00 - Abertura" (com o grande final) e "NN - Encerramento" (com
o logo da produtora).

**Spec:** `docs/superpowers/specs/2026-11-09-formatura-abertura-encerramento-design.md`

## Global Constraints

- Nenhum arquivo comum é alterado. Há outro chat mexendo no master.
- Os testes rodam com `PYTHONPATH=src ../../.venv/Scripts/python.exe -m pytest`.

## Review Focus

1. **Logo apontando para um arquivo que sumiu:** o encerramento sai com o marcador e sem o
   clipitem. Teste na Tarefa 2.
2. **Roteiro dos clipes que referencia uma mídia fora do catálogo:** o `generate_roteiro` comum
   corrige ou remove. Coberto pelos testes comuns.
3. **Sem música:** os clipes saem sem a faixa de música. Coberto pelo `build_sequence` comum.

### Task 1: Ajustes, contexto e diálogo

- [ ] Testes: `ajustes` (ida e volta, sem arquivo); `contexto_abertura_encerramento` (os trechos
  da spec); `nomes_clipes`; o diálogo grava o logo.
- [ ] Implementar e gravar o commit.

### Task 2: XML com os clipes e o logo, e as entregas

- [ ] Testes: a ordem das sequências; o clipitem do logo no fim do encerramento; o marcador sem o
  logo; as entregas na ordem.
- [ ] Implementar e gravar o commit.

### Task 3: Pipeline e integração

- [ ] Testes: a análise com a mesa de corte; os clipes gerados e gravados (`roteiro_clipes`); a
  falha comum → aviso e a íntegra mantida; trilhas tolerantes (substitui
  `test_colacao_nao_precisa_de_musica`); a integração com as duas sequências.
- [ ] Implementar, rodar a suíte, juntar e enviar.
