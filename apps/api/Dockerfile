FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Tell Claude Code where to look for its config inside the container.
    # We bind-mount the host's ~/.claude here at runtime.
    CLAUDE_CONFIG_DIR=/root/.claude

WORKDIR /app

# System deps + Node.js 20 (for the Claude Code CLI). The CLI is a Node package,
# so the Python image needs Node too.
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      gcc \
      pkg-config \
      default-libmysqlclient-dev \
      curl \
      ca-certificates \
      git \
      gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI globally so `claude` is on PATH inside the container.
RUN npm install -g @anthropic-ai/claude-code@latest \
    && npm cache clean --force

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . ./

RUN chmod +x /app/scripts/start.sh

EXPOSE 8000

CMD ["/app/scripts/start.sh"]
