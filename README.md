# Reuse Mesh для AI IDE

Этот репозиторий подключает AI IDE к MCP-серверу Reuse Mesh. Сервер помогает находить готовые компоненты в дружественных репозиториях, следовать правилам переиспользования и передавать обратную связь авторам.

## MCP endpoint

```text
https://litellm.ds-hub-cf.ru/reuse_mesh/mcp
```

Сервер использует Streamable HTTP. Для подключения используйте один из файлов в [`mcp-config/`](mcp-config/).

## Быстрое подключение

### Claude Code

```sh
claude mcp add --transport http reuse-mesh https://litellm.ds-hub-cf.ru/reuse_mesh/mcp
```

### Codex CLI

```sh
codex mcp add reuse-mesh --url https://litellm.ds-hub-cf.ru/reuse_mesh/mcp
```

Если ваша IDE поддерживает импорт MCP-конфигурации, откройте или скопируйте [`.mcp.json`](.mcp.json) в конфигурацию проекта.

Замените `<YOUR_LITELLM_REUSE_MESH_TOKEN>` на один из выданных virtual keys. Не публикуйте его в Git, issue или чате. Доступ к upstream `teamrepomcp.ds-hub-cf.ru` предназначен только для LiteLLM.

## Как агент должен работать

1. Перед новой реализацией вызывает `get_rules` и `search_components`.
2. Сначала оценивает найденные кандидаты.
3. При отказе или идее улучшения вызывает `submit_feedback`.
4. Не передаёт через feedback секреты, персональные данные и закрытый код.

Полные инструкции лежат в [`rules.md`](rules.md). MCP обновляет эти правила автоматически: кэш не более 60 секунд; для немедленного обновления вызовите `get_rules` с `force_refresh: true`.

## Доступные инструменты MCP

| Инструмент | Назначение |
| --- | --- |
| `get_rules` | Получить актуальные правила переиспользования. |
| `list_repositories` | Посмотреть дружественные источники. |
| `search_components` | Найти подходящий код/модель. |
| `submit_feedback` | Зафиксировать reuse, отказ или предложение улучшения. |

## Дружественные источники

- [Uralman на Hugging Face](https://huggingface.co/uralman)
- [AI Sage на Hugging Face](https://huggingface.co/ai-sage)
- [AI Forever на Hugging Face](https://huggingface.co/ai-forever)
- [AI Forever на GitHub](https://github.com/ai-forever)
