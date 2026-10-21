#!/bin/sh
# Start the simulated machines, then the agent pointed at them and at the API.
#   EURVEDA_URL   where the agent pushes (default http://api:8001, the API on the compose network)
#   EURVEDA_TOKEN the connector token (the API creates the connector from PLANT_SIM_TOKEN / PLANT_SIM_ORG)
#   Speed, patterns and machines are set in Eurveda: Playground → Plant data → Live → Sim engine.
set -e
: "${EURVEDA_TOKEN:?set PLANT_SIM_TOKEN in .env}"
# settings (speed, patterns, machines on/off) come from Eurveda's Sim engine panel, read every 5 s with the token
python simulator.py --config-url "${EURVEDA_URL:-http://api:8001}/api/ingest/plant-data/sim-config" &
sleep 4
cat > /tmp/config.yaml <<CFG
eurveda:
  url: ${EURVEDA_URL:-http://api:8001}
  token_env: EURVEDA_TOKEN
  push_every_s: ${PUSH_EVERY_S:-15}
  buffer: /tmp/eurveda-buffer.sqlite
  buffer_max_rows: 20000
machines:
  - name: RMG-1
    format: rmg
    protocol: opcua
    endpoint: opc.tcp://localhost:4840/eurveda-sim/
    poll_s: ${POLL_S:-5}
    product: {fixed: "Paracetamol Tablets IP 500 mg"}
    batch: {node: "ns=2;s=RMG1.BatchNo"}
    tags:
      dry_mix_kg: "ns=2;s=RMG1.DryMixKg"
      binder_kg: "ns=2;s=RMG1.BinderKg"
      wet_mix_min: "ns=2;s=RMG1.WetMixMin"
      impeller_kw: "ns=2;s=RMG1.ImpellerKW"
  - name: BLENDER-1
    format: blender
    protocol: opcua
    endpoint: opc.tcp://localhost:4840/eurveda-sim/
    poll_s: ${POLL_S:-5}
    product: {fixed: "Paracetamol Tablets IP 500 mg"}
    batch: {node: "ns=2;s=BLEND1.BatchNo"}
    tags:
      blend_min: "ns=2;s=BLEND1.BlendMin"
      blender_rpm: "ns=2;s=BLEND1.SpeedRPM"
  - name: FBD-1
    format: fbd
    protocol: opcua
    endpoint: opc.tcp://localhost:4840/eurveda-sim/
    poll_s: ${POLL_S:-5}
    product: {fixed: "Paracetamol Tablets IP 500 mg"}
    batch: {node: "ns=2;s=FBD1.BatchNo"}
    tags:
      inlet_c: "ns=2;s=FBD1.InletTemp"
      outlet_c: "ns=2;s=FBD1.OutletTemp"
      product_c: "ns=2;s=FBD1.ProductTemp"
      inlet_rh_pct: "ns=2;s=FBD1.InletRH"
      air_m3_h: "ns=2;s=FBD1.AirFlow"
      lod_pct: "ns=2;s=FBD1.LOD"
      elapsed_min: "ns=2;s=FBD1.ElapsedMin"
  - name: PRESS-1
    format: press
    protocol: opcua
    endpoint: opc.tcp://localhost:4840/eurveda-sim/
    poll_s: ${POLL_S:-5}
    product: {fixed: "Paracetamol Tablets IP 500 mg"}
    batch: {node: "ns=2;s=PRESS1.BatchNo"}
    tags:
      force_kn: "ns=2;s=PRESS1.ForceKN"
      precompression_kn: "ns=2;s=PRESS1.PrecompKN"
      tablet_weight_mg: "ns=2;s=PRESS1.TabletWeightMg"
      punch_diameter_mm: "ns=2;s=PRESS1.PunchDiameterMm"
      press_rpm: "ns=2;s=PRESS1.TurretRPM"
CFG
exec python eurveda_agent.py --config /tmp/config.yaml
