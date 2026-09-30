FROM node:22-alpine AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json ./
COPY src ./src
COPY miniapp-frontend ./miniapp-frontend
COPY assets ./assets
RUN npm run build

FROM node:22-alpine AS runtime

ENV NODE_ENV=development
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY --from=build /app/dist ./dist
COPY --from=build /app/miniapp-frontend/dist ./miniapp-frontend/dist
COPY assets ./assets
USER node
EXPOSE 3000 8787
STOPSIGNAL SIGTERM
CMD ["npm", "run", "start:bot"]
