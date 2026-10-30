FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libpq-dev curl \
        # WeasyPrint runtime deps (PDF reports). pango/cairo/
        # gdk-pixbuf/glib are dlopen'd at first import; without them the
        # report endpoint crashes with "OSError: cannot load library
        # 'libpango-1.0.so.0'" / "gobject-2.0-0". Adds ~30 MB.
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b \
        libcairo2 libgdk-pixbuf-2.0-0 libglib2.0-0 \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]
