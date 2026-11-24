#!/usr/bin/env python
"""X9 teacher: a local Qwen2.5-7B-Instruct judges facility-name pairs.

The teacher sees exactly what the student cross-encoder sees, two records as
``name | LGA``, and answers whether they are the same health facility. Its
score is ``P(Yes) / (P(Yes) + P(No))`` from the next-token logits, so no text is
generated or parsed. It runs on this machine (4-bit, bitsandbytes); no pair
leaves it.

    python data/scripts/x9_teacher.py --pairs <jsonl in> --out <jsonl out>

Pass ``--shots`` to add worked examples (X9 uses six from the training states).

Each input line is ``{"id": ..., "a": "name | LGA", "b": "name | LGA"}``. Each
output line adds ``"teacher": p``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

MODEL = "Qwen/Qwen2.5-7B-Instruct"
PROMPT = (
    "Two records come from Nigerian health facility registries. Each is written as "
    "'facility name | local government area (LGA)'.\n"
    "Record A: {a}\n"
    "Record B: {b}\n"
    "Do the two records refer to the same health facility? Spelling variants, missing "
    "spaces, abbreviations (PHC, BHC, CHC, MCH) and different facility-type words "
    "(health post, clinic, primary health center) can name the same facility. Different "
    "numbers (Zango 1, Zango 2), different place names, or different named owners usually "
    "mean different facilities. Answer with one word: Yes or No."
)


def with_shots(shots: list[dict]) -> str:
    """The prompt with worked examples (drawn from the training states, never from labels)."""
    ex = "\n".join(f"Record A: {r['a']}\nRecord B: {r['b']}\n"
                   f"Same facility: {'Yes' if r['hard'] else 'No'}\n" for r in shots)
    ex = ex.replace("{", "{{").replace("}", "}}")
    return PROMPT.replace("Record A: {a}", "Examples:\n" + ex + "\nNow decide.\nRecord A: {a}")


class Teacher:
    def __init__(self, model: str = MODEL, four_bit: bool = True, prompt: str = PROMPT) -> None:
        self.prompt = prompt
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(model)
        self.tok.padding_side = "left"
        quant = (BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16,
                                    bnb_4bit_quant_type="nf4") if four_bit else None)
        self.model = AutoModelForCausalLM.from_pretrained(
            model, quantization_config=quant, dtype=torch.bfloat16, device_map="cuda").eval()
        self.yes = self.tok.encode("Yes", add_special_tokens=False)[0]
        self.no = self.tok.encode("No", add_special_tokens=False)[0]
        self.name = model

    def prompts(self, pairs: list[tuple[str, str]]) -> list[str]:
        return [self.tok.apply_chat_template(
            [{"role": "user", "content": self.prompt.format(a=a, b=b)}],
            tokenize=False, add_generation_prompt=True) for a, b in pairs]

    def score(self, pairs: list[tuple[str, str]], batch: int = 32) -> list[float]:
        out: list[float] = []
        with self.torch.inference_mode():
            for i in range(0, len(pairs), batch):
                enc = self.tok(self.prompts(pairs[i:i + batch]), return_tensors="pt",
                               padding=True).to("cuda")
                logits = self.model(**enc).logits[:, -1, :].float()
                two = self.torch.stack([logits[:, self.yes], logits[:, self.no]], dim=1)
                out.extend(self.torch.softmax(two, dim=1)[:, 0].cpu().tolist())
        return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pairs", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--shots", type=Path, help="JSON with worked examples (x9 fewshot.json)")
    args = ap.parse_args()
    rows = [json.loads(line) for line in args.pairs.open(encoding="utf-8")]
    done = {}
    if args.out.exists():
        done = {r["id"]: r for r in map(json.loads, args.out.open(encoding="utf-8"))}
    todo = [r for r in rows if r["id"] not in done]
    prompt = PROMPT
    if args.shots:
        prompt = with_shots(json.loads(args.shots.read_text(encoding="utf-8"))["shots"])
    teacher = Teacher(prompt=prompt)
    started = time.time()
    with args.out.open("a", encoding="utf-8") as fh:
        for i in range(0, len(todo), 512):
            chunk = todo[i:i + 512]
            for r, p in zip(chunk, teacher.score([(r["a"], r["b"]) for r in chunk], args.batch),
                            strict=True):
                fh.write(json.dumps({**r, "teacher": round(p, 6)}) + "\n")
            fh.flush()
            rate = (i + len(chunk)) / (time.time() - started)
            print(f"{i + len(chunk)}/{len(todo)} pairs, {rate:.1f}/s", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
