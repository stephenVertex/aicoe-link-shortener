#!/usr/bin/env python3
"""Print the first 100 prime numbers."""


def first_n_primes(n: int) -> list[int]:
    primes = []
    candidate = 2
    while len(primes) < n:
        if all(candidate % p != 0 for p in primes if p * p <= candidate):
            primes.append(candidate)
        candidate += 1
    return primes


if __name__ == "__main__":
    primes = first_n_primes(100)
    for i, p in enumerate(primes, 1):
        print(f"{i:3}. {p}")
