# Eurveda edge agent

Reads plant machines over **OPC UA** or **Modbus TCP**, read-only, and streams the readings to Eurveda
(Playground → Plant data → Live), where they join your batch records and the failure tree.

## Install (on a PC or small box on the plant network that can reach the machines and the internet)

```
python -m pip install -r requirements.txt
```

Python 3.10 or newer. Nothing is written to any machine; readings wait in a local SQLite file while the internet is down.

## Set up

1. In Eurveda: **Plant data → Live → Add a connector**. Copy the token (shown once).
2. Download `config.yaml` from the same page (your Eurveda address is filled in) and list your machines.
   Find a machine's OPC UA tags with:
   ```
   python eurveda_agent.py --browse opc.tcp://<machine-ip>:4840
   ```
   For Modbus, the register addresses are in the machine's manual or its PLC program.
3. Check every tag reads what the machine's screen shows:
   ```
   python eurveda_agent.py --config config.yaml --check
   ```
4. Run it (as a service in production: Windows Task Scheduler / NSSM, or systemd):
   ```
   set EURVEDA_TOKEN=evd_...        (Windows)      export EURVEDA_TOKEN=evd_...   (Linux)
   python eurveda_agent.py --config config.yaml
   ```

The batch number has to come from somewhere: a machine tag (`batch: {node: ...}`), a text file the operator updates
(`batch: {file: ...}`), or a fixed value. Readings without a batch number are skipped.

## Try it without a plant

```
python simulator.py --fault short-dry --fault-every 3       # OPC UA dryer + press on opc.tcp://localhost:4840/eurveda-sim/
python eurveda_agent.py --config config.example.yaml --check
```

`config.example.yaml` already points at the simulator. `--modbus 5020` also serves the press over Modbus TCP.

## Security

- Use OPC UA `Basic256Sha256,SignAndEncrypt` with certificates your IT issues when the machine supports it.
- The agent only makes outbound HTTPS calls to Eurveda; no inbound port is needed on the plant network.
- Revoking the connector in Eurveda stops the agent (it exits on the next push).
