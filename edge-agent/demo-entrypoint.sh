#!/bin/sh
# Start the simulated machines, then the agent pointed at them and at the API.
#   EURVEDA_URL   where the agent pushes (default http://api:8001, the API on the compose network)
#   EURVEDA_TOKEN the connector token (the API creates the connector from PLANT_SIM_TOKEN / PLANT_SIM_ORG)
#   SIM_SPEED     simulated seconds per real second (default 30: a 60-minute drying takes 2 minutes)
#   SIM_FAULT     none | short-dry | over-compress | humid-air, on every SIM_FAULT_EVERY-th batch (default short-dry, 3)
set -e
: "${EURVEDA_TOKEN:?set PLANT_SIM_TOKEN in .env}"
python simulator.py --speed "${SIM_SPEED:-30}" --fault "${SIM_FAULT:-short-dry}" --fault-every "${SIM_FAULT_EVERY:-3}" &
sleep 4
cat > /tmp/config.yaml <<CFG
eurveda:
  url: ${EURVEDA_URL:-http://api:8001}
  token_env: EURVEDA_TOKEN
  push_every_s: ${PUSH_EVERY_S:-15}
  buffer: /tmp/eurveda-buffer.sqlite
  buffer_max_rows: 20000
machines:
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
