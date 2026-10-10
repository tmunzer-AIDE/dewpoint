# SPDX-License-Identifier: Apache-2.0
# D12's Temporal target (2b-4b M4): built in the pinned golang, run on the pinned distroless base, both by digest.
# The build vets, runs every test (the classification against the compiled-in services among them), then builds a
# static binary, stamped with its build context's identity (every file's SHA-256 by path, in C order, hashed: the
# proofs refuse an image whose inventory doesn't name this tree's, backend/tests/proofs/environment.SOURCE_PIPELINE).
# Modules come from the proxy and are checked against go.sum; for an offline build, pass an already verified module
# cache as a named context and no network:
#
#   docker build --network none --build-context gomod=<module cache> --build-arg GOPROXY=off -t <tag> deploy/temporal
FROM scratch AS gomod

FROM golang:1.26.8@sha256:0f063af2d465d8dcae54cce04278ada488b96f77b42449c8d071e47d016cc65a AS build
ARG GOPROXY=https://proxy.golang.org
ENV GOPROXY=${GOPROXY} GOFLAGS=-mod=readonly CGO_ENABLED=0
WORKDIR /src
COPY . .
RUN --mount=type=bind,from=gomod,target=/go/pkg/mod,rw \
    --mount=type=cache,target=/root/.cache/go-build \
    identity="$(find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)" \
    && go mod verify \
    && go vet ./... \
    && go test -count=1 ./... \
    && go build -trimpath -buildvcs=false -ldflags="-s -w -X main.source=${identity}" -o /out/temporal-server . \
    && go build -trimpath -buildvcs=false -ldflags="-s -w" -o /out/proofclient ./cmd/proofclient

# The proof's exhaustive gRPC caller (`--target proofclient`): never part of the server's image.
FROM gcr.io/distroless/static-debian12:nonroot@sha256:afa5c872c891853ca7fcf1f12c3edb23f7eeef36189728842dd51042ff57f7ab AS proofclient
COPY --from=build /out/proofclient /usr/local/bin/proofclient
USER nonroot
ENTRYPOINT ["/usr/local/bin/proofclient"]

# The server: the default target.
FROM gcr.io/distroless/static-debian12:nonroot@sha256:afa5c872c891853ca7fcf1f12c3edb23f7eeef36189728842dd51042ff57f7ab AS server
COPY --from=build /out/temporal-server /usr/local/bin/temporal-server
COPY config/dynamicconfig.yaml /etc/temporal/dynamicconfig.yaml
USER nonroot
ENTRYPOINT ["/usr/local/bin/temporal-server"]
