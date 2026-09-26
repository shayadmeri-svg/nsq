"""Structure-based chemistry for the lab.

molecule.py       RDKit descriptors, McGowan volume, solubility models (ESOL, GSE),
                  provisional BCS class, 2D depiction
thermo_props.py   melting point / enthalpy of fusion (PubChem > chemicals DB > Joback),
                  solvent properties (thermo), solubility-vs-temperature curves
product.py        drug-product models: dissolution (Noyes-Whitney / Hintz-Johnson),
                  compaction (Heckel + Ryshkewitch-Duckworth), fluid-bed psychrometrics
crystallization.py  batch cooling crystallisation (method of moments) and the
                  request format shared with the PharmaPy sidecar (sim/)

Every function returns the assumptions it used, so the UI can show where a
number came from instead of presenting a constant as fact.
"""
