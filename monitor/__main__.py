"""Point d'entree du module monitor : `python -m monitor`.

Ecoute les mints du contrat token configure (`MONITOR_TOKEN_ADDRESS`) sur le
RPC Fuji (`FUJI_RPC_URL`) et affiche chaque `MintEvent` en JSON (une ligne par
evenement). Sans adresse de token ni RPC, affiche un message et s'arrete.
"""

from __future__ import annotations

import logging

from monitor.config import ENV_RPC_URL, ENV_TOKEN_ADDRESS, load_monitor_config
from monitor.listener import ChainListener


def main() -> None:
    """Point d'entree executable."""
    # Les erreurs RPC retentees et la « surveillance aveugle » (issue #74)
    # passent par `logging` : sans configuration, elles seraient invisibles.
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s"
    )
    config = load_monitor_config()
    missing = [
        name
        for name, value in (
            (ENV_RPC_URL, config.rpc_url),
            (ENV_TOKEN_ADDRESS, config.token_address),
        )
        if not value
    ]
    if missing:
        print(
            f"monitor : {', '.join(missing)} non renseignee(s) dans .env. "
            "Rien a ecouter (aucun contrat deploye, voir contracts/DEPLOYMENTS.md)."
        )
        return
    print(f"monitor : ecoute des mints du token {config.token_address} ...")
    for event in ChainListener(config).stream_mint_events():
        print(event.model_dump_json())


if __name__ == "__main__":
    main()
