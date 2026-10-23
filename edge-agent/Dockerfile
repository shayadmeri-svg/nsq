# Plant simulator + edge agent in one small container (docker compose --profile demo): an OPC UA dryer and press
# (simulator.py) read by the real agent (eurveda_agent.py) and streamed to the API, so the live view runs without a
# plant or a laptop. The same agent is what a plant installs; only the machines here are simulated.
FROM python:3.12-slim
WORKDIR /agent
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY eurveda_agent.py simulator.py sim_defaults.json sim_machines.json demo-entrypoint.sh ./
RUN chmod +x demo-entrypoint.sh && useradd -r agent && chown -R agent /agent
USER agent
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["./demo-entrypoint.sh"]
