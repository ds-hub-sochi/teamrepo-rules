# Reuse Mesh для AI IDE

Этот репозиторий подключает AI IDE к MCP-серверу Reuse Mesh. Сервер помогает находить готовые модели, датасеты, библиотеки и исходный код в дружественных источниках, следовать правилам переиспользования и передавать обратную связь авторам.

## Подключение к любой AI IDE

Передайте вашей AI IDE [типовое правило подключения](MCP_SETUP_RULE.md). Оно сначала попросит выбрать область настройки — только текущий проект или глобально для пользователя — и затем применит нативный способ этой IDE.

Endpoint Reuse Mesh: `https://litellm.ds-hub-cf.ru/reuse_mesh/mcp`. Для доступа потребуется выданный LiteLLM virtual key. Не публикуйте его в Git, issue или чате.

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
| `search_components` | Найти подходящую модель, датасет, библиотеку или репозиторий. |
| `submit_feedback` | Зафиксировать reuse, отказ или предложение улучшения. |
| `get_feedback` | Получить сводку или полные безопасные записи feedback по источнику. |

## Дружественные источники

- [Uralman на Hugging Face](https://huggingface.co/uralman)
- [AI Sage на Hugging Face](https://huggingface.co/ai-sage)
- [AI Forever на Hugging Face](https://huggingface.co/ai-forever)
- [AI Forever на GitHub](https://github.com/ai-forever)
- [Frontier AI Next на GitHub](https://github.com/frontier-ai-next)
