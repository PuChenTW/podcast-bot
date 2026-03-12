TRANSLATIONS = {
    "en": {
        "start_message": (
            "Podcast Bot\n\n"
            "/subscribe — subscribe to a podcast\n"
            "/unsubscribe — remove a subscription\n"
            "/list — show your subscriptions\n"
            "/digest — get a summary of a specific episode\n"
            "/setprompt — customize summarization style per podcast\n"
            "/language — set language"
        ),
        # Subscribe / Unsubscribe / List
        "subscribe_prompt": "Please enter the RSS feed URL or Apple Podcasts link:",
        "fetching_feed": "Fetching feed...",
        "fetch_error": "Could not fetch feed. Check the URL and try again.",
        "invalid_feed": "Invalid RSS feed. Check the URL and try again.",
        "subscribed": 'Subscribed to "{title}". Future episodes will be summarized.',
        "no_subscriptions": "No subscriptions yet.",
        "no_subscriptions_use_subscribe": "No subscriptions yet. Use /subscribe.",
        "your_subscriptions": "Your subscriptions:",
        "unsub_choose": "Select the podcast to unsubscribe from:",
        "sub_not_found": "Subscription not found.",
        "unsub_success": 'Unsubscribed from "{title}".',
        "cancel_btn": "Cancel",
        "canceled": "Canceled.",
        # Digest
        "no_subs_please_subscribe": "No subscriptions found. Please /subscribe first.",
        "select_podcast": "Select a podcast:",
        "choose_episode": "Choose an episode from {title}:",
        "no_episodes_found": "No episodes found in this feed.",
        "fetching_episode": "Fetching episode...",
        "ep_data_expired": "Episode data expired. Run /digest again.",
        "transcription_skipped": "Transcription skipped. Using description only.",
        "transcribing": "Transcribing audio...",
        "summarizing": "Summarizing...",
        "ep_not_found": "Episode not found in feed.",
        "error_generating": "Error generating summary. Please try again.",
        # Set prompt
        "setprompt_intro": "Select a podcast to customize its prompt:",
        "setprompt_choose_action": "Current custom prompt for {title}:\n\n<blockquote>{prompt}</blockquote>\n\nWhat would you like to do?",
        "setprompt_no_prompt": "No custom prompt set for {title}.\n\nWhat would you like to do?",
        "action_keep": "Keep Current",
        "action_manual": "Manual Input",
        "action_auto": "Auto Generate",
        "action_reset": "Reset to Default",
        "prompt_input_request": "Please enter the summarize prompt for this podcast:",
        "prompt_auto_request": "Please briefly describe the style or key points for this podcast's summary:",
        "prompt_not_found": "Could not find the pending prompt. Please run /setprompt again.",
        "prompt_saved": "Saved ✓",
        "prompt_reset": "Reset to default prompt ✓",
        "generating": "Generating...",
        "generate_error": "Could not find a description, please run /setprompt again.",
        "regenerating": "Regenerating...",
        "generated_preview": "Generated prompt:\n\n<blockquote>{prompt}</blockquote>\n\nKeep this prompt?",
        "action_accept": "Accept",
        "action_retry": "Try Again",
        # Language
        "language_prompt": "Please select your language:",
        "language_set": "Language set to English.",
    },
    "zh-tw": {
        "start_message": (
            "Podcast Bot\n\n"
            "/subscribe — 訂閱 podcast\n"
            "/unsubscribe — 取消訂閱\n"
            "/list — 顯示訂閱列表\n"
            "/digest — 獲取特定單集的摘要\n"
            "/setprompt — 自訂不同 podcast 的摘要風格\n"
            "/language — 設定語言"
        ),
        # Subscribe / Unsubscribe / List
        "subscribe_prompt": "請輸入 RSS feed 網址或 Apple Podcasts 連結：",
        "fetching_feed": "正在獲取 feed...",
        "fetch_error": "無法獲取 feed，請檢查網址後再試一次。",
        "invalid_feed": "無效的 RSS feed，請檢查網址後再試一次。",
        "subscribed": "已訂閱「{title}」。未來的單集將會自動摘要。",
        "no_subscriptions": "目前沒有任何訂閱。",
        "no_subscriptions_use_subscribe": "目前沒有任何訂閱，請使用 /subscribe 訂閱。",
        "your_subscriptions": "你的訂閱列表：",
        "unsub_choose": "選擇要取消訂閱的 podcast：",
        "sub_not_found": "找不到該訂閱。",
        "unsub_success": "已取消訂閱「{title}」。",
        "cancel_btn": "取消",
        "canceled": "已取消。",
        # Digest
        "no_subs_please_subscribe": "沒有找到任何訂閱，請先使用 /subscribe 訂閱。",
        "select_podcast": "請選擇一個 podcast：",
        "choose_episode": "請從 {title} 選擇一個單集：",
        "no_episodes_found": "在此 feed 中找不到任何單集。",
        "fetching_episode": "正在獲取單集...",
        "ep_data_expired": "單集資料已過期，請重新執行 /digest。",
        "transcription_skipped": "略過語音辨識，僅使用說明文字。",
        "transcribing": "正在轉錄音檔...",
        "summarizing": "正在生成摘要...",
        "ep_not_found": "在 feed 中找不到該單集。",
        "error_generating": "生成摘要時發生錯誤，請再試一次。",
        # Set prompt
        "setprompt_intro": "選擇一個 podcast 來設定自訂 prompt：",
        "setprompt_choose_action": "目前 {title} 的自訂 prompt 為：\n\n<blockquote>{prompt}</blockquote>\n\n請選擇你要執行的動作：",
        "setprompt_no_prompt": "{title} 目前沒有設定自訂 prompt。\n\n請選擇你要執行的動作：",
        "action_keep": "保留目前設定",
        "action_manual": "手動輸入",
        "action_auto": "自動生成",
        "action_reset": "還原預設",
        "prompt_input_request": "請輸入這個 podcast 的 summarize prompt：",
        "prompt_auto_request": "請簡短描述這個 podcast 的風格或你想要的摘要重點：",
        "prompt_not_found": "找不到待確認的 prompt，請重新執行 /setprompt。",
        "prompt_saved": "已儲存 ✓",
        "prompt_reset": "已還原為預設 prompt ✓",
        "generating": "生成中...",
        "generate_error": "找不到描述，請重新執行 /setprompt。",
        "regenerating": "重新生成中...",
        "generated_preview": "生成的 prompt 如下：\n\n<blockquote>{prompt}</blockquote>\n\n是否使用此 prompt？",
        "action_accept": "接受",
        "action_retry": "再試一次",
        # Language
        "language_prompt": "請選擇你的語言設定：",
        "language_set": "已將語言設定為繁體中文。",
    },
}


def gettext(lang: str, key: str, **kwargs) -> str:
    # Default to zh-tw if language is unknown or fallback
    if lang not in TRANSLATIONS:
        lang = "zh-tw"

    text = TRANSLATIONS[lang].get(key, TRANSLATIONS["zh-tw"].get(key, key))
    if kwargs:
        return text.format(**kwargs)
    return text
