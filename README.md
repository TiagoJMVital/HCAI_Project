# pcs-agent

Proposer–Critic–Defer: assistente de calendário com raciocínio de trade-offs e
autonomia aprendida. Projeto de HCAI, Universidade de Coimbra.

## Estrutura

```
data/profile.json       perfil de preferências
data/scenarios/         cenários do benchmark
schemas/                JSON Schemas exportados dos modelos
src/models.py           modelos Pydantic
src/llm.py              cliente Ollama com saída estruturada
src/make_seed_scenarios.py   gera os cenários iniciais
src/validate_data.py    valida perfil, cenários e split treino/teste
```

## Instalações/Comandos
winget install Git.Git
winget install Python.Python.3.12
winget install Microsoft.VisualStudioCode
wsl --install
(Docker para n8n)
winget install Docker.DockerDesktop
(Ollama)
winget install Ollama.Ollama
ollama pull llama3.1:8b
ollama run llama3.1:8b "Responde apenas com JSON: {\"ok\": true}" (para testar se está a funcionar)
curl http://localhost:11434/api/tags (para testar se a API está a correr)
(n8n)
docker volume create n8n_data
docker run -d --name n8n --restart unless-stopped -p 5678:5678 -e GENERIC_TIMEZONE=Europe/Lisbon -e TZ=Europe/Lisbon -v n8n_data:/home/node/.n8n docker.n8n.io/n8nio/n8n
(na pasta do projeto criar o venv e as dependencias)
python -m venv .venv
pip install pandas numpy scikit-learn matplotlib requests pydantic python-dotenv pytest jupyter

## Testar

```powershell
.venv\Scripts\Activate.ps1
python src\validate_data.py
python -m pytest -q tests
python eval\run_config_a.py --only soft_gym_01
```