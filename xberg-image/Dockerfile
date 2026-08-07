# Official xberg extraction server + Hebrew Tesseract data.
#
# The stock image ships eng/ara/rus/…/hin but NOT heb, so OCR with language
# "heb" fails on it. This adds one apt layer (seconds to build — no Rust).
FROM ghcr.io/xberg-io/xberg:1.0.14

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr-heb \
    && rm -rf /var/lib/apt/lists/*
