"""Verificações reais, mínimas e explícitas da API IAedu, sem dados pessoais."""
from __future__ import annotations

import argparse
import sys

from pydantic import BaseModel

from llm import IAeduProvider, LLMError


class CheckResponse(BaseModel):
    ok: bool


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("connectivity", "structured"), required=True)
    args = parser.parse_args()
    client = IAeduProvider()
    try:
        if args.mode == "connectivity":
            client.generate_text("Responde com a palavra OK.")
            print("IAedu: resposta de streaming recebida.")
        else:
            result = client.generate_structured(
                "Devolve o objeto pedido com ok igual a true.", CheckResponse)
            if not result.ok:
                print("IAedu: JSON válido, mas valor inesperado.", file=sys.stderr)
                return 1
            print("IAedu: JSON estruturado validado.")
    except LLMError as exc:
        print(f"IAedu: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
