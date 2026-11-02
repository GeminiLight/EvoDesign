FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production PORT=7860
RUN addgroup -g 1001 -S evodesign && adduser -u 1001 -S evodesign -G evodesign -s /bin/sh
COPY --chown=evodesign:evodesign static/ ./static/
COPY --chown=evodesign:evodesign api/ ./api/
COPY --chown=evodesign:evodesign shared/ ./shared/
COPY --chown=evodesign:evodesign deploy/ ./deploy/
COPY LICENSE ./LICENSE
USER evodesign
EXPOSE 7860
CMD ["node", "deploy/modelscope/server.mjs"]
