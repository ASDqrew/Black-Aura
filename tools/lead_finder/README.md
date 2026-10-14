# Beauty Lead Finder

Ищет в публичных данных OpenStreetMap московских бьюти-мастеров и салоны, оценивает наличие сайта, онлайн-записи и контактов, затем готовит персональное первое сообщение.

## Запуск

```bash
cd /workspace/Black-Aura
python3 tools/lead_finder/lead_finder.py --min-score 50 --limit 100
```

Результат появится в `lead-output/leads.csv` и `lead-output/leads.html`. HTML-отчёт позволяет отфильтровать лиды по приоритету и скопировать готовое сообщение.

По будням в 12:00 по Екатеринбургу GitHub Actions запускает поиск автоматически. Готовые файлы хранятся семь дней в artifact `beauty-leads-moscow` соответствующего запуска workflow **Beauty Lead Finder**. Там же можно запустить поиск вручную через **Run workflow**.

Для повторной обработки уже загруженного ответа без обращения к сети:

```bash
python3 tools/lead_finder/lead_finder.py \
  --input tools/lead_finder/fixtures/overpass_sample.json \
  --output-dir /tmp/beauty-leads-demo
```

Если основной Overpass недоступен, можно указать совместимый сервер:

```bash
OVERPASS_URL=https://overpass.example/api/interpreter \
python3 tools/lead_finder/lead_finder.py
```

## Как считается приоритет

- **A** — нет полноценного сайта, но есть онлайн-запись и/или хороший контакт.
- **B** — сайта нет, контакт есть, но данных для персонализации меньше.
- **C** — слабый контакт или уже есть отдельный сайт.

Социальные сети, YCLIENTS, DIKIDI и страницы-ссылки не считаются полноценным сайтом. Перед отправкой сообщения контакт нужно быстро проверить вручную: система только готовит лид и черновик, сообщения сама не отправляет.
