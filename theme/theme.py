from theme.themes import THEMES

def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip('#')
    return tuple(int(value[i:i+2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return '#{0:02X}{1:02X}{2:02X}'.format(*rgb)


def _blend(color_a: str, color_b: str, amount: float) -> str:
    amount = max(0.0, min(1.0, amount))
    ra, ga, ba = _hex_to_rgb(color_a)
    rb, gb, bb = _hex_to_rgb(color_b)
    blended = (
        int(ra + (rb - ra) * amount),
        int(ga + (gb - ga) * amount),
        int(ba + (bb - ba) * amount),
    )
    return _rgb_to_hex(blended)



def apply_theme(style, theme_key):
    style.theme_use("clam")
    theme = THEMES.get(theme_key, THEMES["nocturne"])
    button_hover = theme.get("button_hover") or _blend(theme["button_bg"], theme["accent"], 0.25)
    button_pressed = theme.get("button_pressed") or _blend(theme["button_bg"], theme["accent"], 0.4)
    primary_hover = theme.get("primary_hover") or _blend(theme["accent"], "#FFFFFF", 0.12)


    # Base surfaces
    style.configure("TFrame", background=theme["main_bg"])
    style.configure("TLabel", background=theme["main_bg"], foreground=theme["text"])

    # Text variations
    style.configure(
        "Muted.TLabel",
        background=theme["main_bg"],
        foreground=theme.get("muted_text", theme["text"]),
        font=("Segoe UI", 9)
    )
    style.configure(
        "Heading.TLabel",
        background=theme["main_bg"],
        foreground=theme["text"],
        font=("Segoe UI", 15, "bold")
    )
    style.configure(
        "Status.TLabel",
        background=theme["main_bg"],
        foreground=theme.get("muted_text", theme["text"]),
        font=("Segoe UI", 9)
    )

    # Sidebar / Navigation
    style.configure("CustomBackdrop.TFrame", background=theme["sidebar"])
    style.configure("Nav.TLabel", background=theme["sidebar"], foreground=theme["text"])
    style.configure(
        "Nav.TButton",
        background=theme["button_bg"],
        foreground=theme["button_fg"],
        relief="flat",
        padding=(14, 10),
        font=("Segoe UI", 11, "bold"),
        borderwidth=0
    )
    style.map(
        "Nav.TButton",
        background=[("active", theme["accent"]), ("pressed", theme["accent_hover"])],
        foreground=[("active", "#FFFFFF"), ("pressed", "#FFFFFF")]
    )

    # Cards & panels
    style.configure("Card.TFrame", background=theme["card_bg"], relief="flat", padding=24)
    style.configure("Panel.TFrame", background=theme["card_bg"])

    style.configure("FileAI.TFrame", background=theme["chat_bg"], relief="flat")
    style.configure("ChatView.TFrame", background=theme["chat_bg"], relief="flat")
    style.configure("ChatFrame.TFrame", background=theme["chat_bg"], relief="flat")
    style.configure("ChatEntry.TFrame", background=theme["chat_bg"], relief="flat")
    style.configure("ChatHeader.TFrame", background=theme["chat_bg"], relief="flat")

    style.configure(
        "ChatHeader.Title.TLabel",
        background=theme["chat_bg"],
        foreground=theme["text"],
        font=("Segoe UI", 14, "bold")
    )
    style.configure(
        "ChatHeader.Subtitle.TLabel",
        background=theme["chat_bg"],
        foreground=theme.get("muted_text", theme["text"]),
        font=("Segoe UI", 10)
    )
    style.configure(
        "Badge.TLabel",
        background=theme["accent"],
        foreground="#FFFFFF",
        font=("Segoe UI", 9, "bold"),
        padding=(8, 2)
    )

    # Entry surfaces
    style.configure("InputWrapper.TFrame", background=theme.get("input_border", theme["card_bg"]))
    style.configure("InputInner.TFrame", background=theme["chat_bg"], relief="flat")

    style.configure(
        "TEntry",
        fieldbackground=theme["input_bg"],
        foreground=theme["text"],
        bordercolor=theme.get("input_border", theme["divider"]),
        padding=6,
        relief="flat"
    )

    # Tree / file lists
    style.configure(
        "Treeview",
        background=theme["file_bg"],
        fieldbackground=theme["file_bg"],
        foreground=theme["text"],
        bordercolor=theme["divider"],
        relief="flat"
    )
    style.map(
        "Treeview",
        background=[("selected", theme["accent"])],
        foreground=[("selected", "#FFFFFF")]
    )

    # Scrollbars
    style.configure(
        "Custom.Vertical.TScrollbar",
        gripcount=0,
        background=theme["button_bg"],
        darkcolor=theme["button_bg"],
        lightcolor=theme["button_bg"],
        troughcolor=theme["chat_bg"],
        bordercolor=theme["chat_bg"],
        arrowsize=10,
        relief="flat"
    )

    # Buttons
    style.configure(
        "TButton",
        background=theme["button_bg"],
        foreground=theme["button_fg"],
        relief="flat",
        padding=(14, 8),
        borderwidth=0,
        focusthickness=1,
        focuscolor=theme["accent"],
        font=("Segoe UI", 10)
    )
    style.map(
        "TButton",
        background=[("pressed", button_pressed), ("active", button_hover)],
        foreground=[("pressed", "#FFFFFF"), ("active", theme["button_fg"])]
    )

    style.configure(
        "Primary.TButton",
        background=theme["accent"],
        foreground="#FFFFFF",
        relief="flat",
        padding=(18, 10),
        borderwidth=0,
        focusthickness=1,
        focuscolor=theme["accent_hover"],
        font=("Segoe UI", 10, "bold")
    )
    style.map(
        "Primary.TButton",
        background=[("pressed", theme["accent_hover"]), ("active", primary_hover)],
        foreground=[("pressed", "#FFFFFF"), ("active", "#FFFFFF")]
    )

    style.configure(
        "Circle.TButton",
        background=theme["chat_bg"],
        foreground=theme["accent"],
        relief="flat",
        padding=6,
        borderwidth=0
    )
    style.map(
        "Circle.TButton",
        background=[("active", theme["accent"])],
        foreground=[("active", "#FFFFFF")]
    )

    # Chat bubbles
    style.configure("UserBubble.TFrame", background=theme["user_bubble_bg"], relief="flat")
    style.configure("AIBubble.TFrame", background=theme["ai_bubble_bg"], relief="flat")
    style.configure("SystemBubble.TFrame", background=theme["system_bubble_bg"], relief="flat")

    style.configure(
        "UserBubble.TLabel",
        background=theme["user_bubble_bg"],
        foreground=theme["user_text"],
        font=("Segoe UI", 10),
        padding=(2, 2)
    )
    style.configure(
        "AIBubble.TLabel",
        background=theme["ai_bubble_bg"],
        foreground=theme["ai_text"],
        font=("Segoe UI", 10),
        padding=(2, 2)
    )
    style.configure(
        "SystemBubble.TLabel",
        background=theme["system_bubble_bg"],
        foreground=theme["system_text"],
        font=("Segoe UI", 10, "italic"),
        padding=(2, 2)
    )

    # Misc labels
    style.configure(
        "Badge.Inverse.TLabel",
        background=theme["chat_bg"],
        foreground=theme["accent"],
        font=("Segoe UI", 9, "bold")
    )

    style.configure(
        "Section.TLabel",
        background=theme["card_bg"],
        foreground=theme["text"],
        font=("Segoe UI", 13, "bold")
    )

    style.configure(
        "Card.TLabel",
        background=theme["card_bg"],
        foreground=theme["text"],
        font=("Segoe UI", 10)
    )

    style.configure(
        "Link.TLabel",
        background=theme["card_bg"],
        foreground=theme["accent"],
        font=("Segoe UI", 10, "underline")
    )

    style.configure(
        "Card.TSeparator",
        background=theme["divider"],
        foreground=theme["divider"]
    )

    style.configure(
        "StatusCard.TFrame",
        background=theme["card_bg"],
        padding=(16, 12)
    )

    style.configure(
        "StatusValue.TLabel",
        background=theme["card_bg"],
        foreground=theme["text"],
        font=("Segoe UI", 24, "bold")
    )

    style.configure(
        "StatusCaption.TLabel",
        background=theme["card_bg"],
        foreground=theme.get("muted_text", theme["text"]),
        font=("Segoe UI", 9)
    )

    style.configure(
        "StatusChip.TLabel",
        background=theme["accent"],
        foreground="#FFFFFF",
        font=("Segoe UI", 9, "bold"),
        padding=(12, 4)
    )
