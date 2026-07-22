from fastapi import APIRouter, Depends

from core import database as db
from core.ai.prompt_engineer import generate_chat_prompt_from_description, generate_prompt_from_description
from web.routers.v1.dependencies import require_subscription
from web.routers.v1.schemas import PromptDraft, PromptDraftRequest, PromptSettings, PromptSettingsPatch

router = APIRouter(prefix="/subscriptions/{subscription_id}", tags=["prompts"])


@router.get(
    "/prompts",
    response_model=PromptSettings,
    operation_id="get_subscription_prompts",
    responses={403: {"description": "Forbidden"}, 404: {"description": "Subscription not found"}},
)
async def get_subscription_prompts(subscription=Depends(require_subscription)):
    """Return custom summary and chat prompts for a subscription.

    A `null` value means the corresponding workflow uses its default prompt.
    """
    return PromptSettings(summary_prompt=subscription.custom_prompt, chat_prompt=subscription.chat_prompt)


@router.patch(
    "/prompts",
    response_model=PromptSettings,
    operation_id="update_subscription_prompts",
    responses={403: {"description": "Forbidden"}, 404: {"description": "Subscription not found"}},
)
async def update_subscription_prompts(body: PromptSettingsPatch, subscription=Depends(require_subscription)):
    """Update custom prompts for a subscription.

    Only fields present in the request are changed. Set a field to `null` to
    restore that workflow's default prompt.
    """
    update_summary = "summary_prompt" in body.model_fields_set
    update_chat = "chat_prompt" in body.model_fields_set
    updates = {}
    if update_summary:
        updates["custom_prompt"] = body.summary_prompt
    if update_chat:
        updates["chat_prompt"] = body.chat_prompt
    await db.update_subscription_prompts(subscription.id, updates)
    return PromptSettings(
        summary_prompt=body.summary_prompt if update_summary else subscription.custom_prompt,
        chat_prompt=body.chat_prompt if update_chat else subscription.chat_prompt,
    )


@router.post(
    "/prompt-drafts",
    response_model=PromptDraft,
    operation_id="create_subscription_prompt_draft",
    responses={403: {"description": "Forbidden"}, 404: {"description": "Subscription not found"}},
)
async def create_subscription_prompt_draft(body: PromptDraftRequest, subscription=Depends(require_subscription)):
    """Generate a custom prompt draft without saving it.

    The requested prompt kind and natural-language description are combined
    with the podcast title. Save the returned draft with the prompts endpoint.
    """
    description = body.description.strip()
    context = f"{subscription.podcast_title}. {description}" if description else subscription.podcast_title
    if body.kind == "chat":
        prompt = await generate_chat_prompt_from_description(context)
    else:
        prompt = await generate_prompt_from_description(context)
    return PromptDraft(prompt=prompt)
