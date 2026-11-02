FROM node:22-alpine
WORKDIR /home/user/app
ENV NODE_ENV=production PORT=7860
COPY --chown=node:node static/ ./static/
COPY --chown=node:node api/ ./api/
COPY --chown=node:node shared/ ./shared/
COPY --chown=node:node deploy/ ./deploy/
COPY LICENSE ./LICENSE
USER node
EXPOSE 7860
CMD ["node", "/home/user/app/deploy/modelscope/server.mjs"]
