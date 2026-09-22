FROM node:22-bookworm-slim

WORKDIR /opt/cleardebt
COPY package.json package-lock.json ./
RUN npm ci

COPY cleardebt-test.mjs /usr/local/bin/cleardebt-test.mjs
ENTRYPOINT ["node", "/usr/local/bin/cleardebt-test.mjs"]
