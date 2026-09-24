"""Name -> recipe registry so the mixer can build sounds lazily by key."""

from . import sfx

# key: (builder, default_volume)
SFX_REGISTRY = {
    # weapons
    "gun_pistol": (sfx.gunshot_suppressed, 0.55),
    "gun_smg": (sfx.gunshot_smg, 0.62),
    "gun_shotgun": (sfx.gunshot_shotgun, 0.72),
    "gun_sniper": (sfx.gunshot_sniper, 0.85),
    "dry_fire": (sfx.dry_fire, 0.5),
    "reload_out": (sfx.reload_mag_out, 0.5),
    "reload_in": (sfx.reload_mag_in, 0.55),
    "reload_charge": (sfx.reload_charge, 0.5),
    "knife_swing": (sfx.knife_swing, 0.5),
    "knife_hit": (sfx.knife_hit, 0.6),
    "impact_stone": (sfx.bullet_impact_stone, 0.45),
    "impact_metal": (sfx.bullet_impact_metal, 0.5),
    "impact_flesh": (sfx.bullet_impact_flesh, 0.55),
    "grenade_pin": (sfx.grenade_pin, 0.5),
    "grenade_bounce": (sfx.grenade_bounce, 0.5),
    "grenade_boom": (sfx.grenade_explosion, 0.95),
    "bullet_whizz": (sfx.bullet_whizz, 0.5),
    # pickups / mission
    "pickup_item": (sfx.pickup_item, 0.6),
    "pickup_ammo": (sfx.pickup_ammo, 0.6),
    "intel": (sfx.intel_download, 0.6),
    "objective_done": (sfx.objective_complete, 0.7),
    "objective_fail": (sfx.objective_failed, 0.7),
    # movement
    "step_concrete": (sfx.footstep_concrete, 0.38),
    "step_gravel": (sfx.footstep_gravel, 0.38),
    "step_grass": (sfx.footstep_grass, 0.34),
    "step_metal": (sfx.footstep_metal, 0.34),
    "jump": (sfx.jump_grunt, 0.4),
    "land": (sfx.land_thud, 0.5),
    "hurt": (sfx.player_hurt, 0.55),
    "death": (sfx.player_death, 0.7),
    # enemies
    "enemy_alert": (sfx.enemy_alert_shout, 0.6),
    "enemy_pain": (sfx.enemy_pain, 0.55),
    "enemy_death": (sfx.enemy_death, 0.6),
    "enemy_step": (sfx.enemy_footstep, 0.22),
    "enemy_reload": (sfx.enemy_reload, 0.4),
    # vehicles
    "truck_horn": (sfx.truck_horn, 0.6),
    "truck_boom": (sfx.truck_destroyed, 0.95),
    # cameras / alarm
    "camera_beep": (sfx.camera_detect_beep, 0.55),
    "camera_break": (sfx.camera_destroyed, 0.6),
    "alarm_cancel": (sfx.alarm_cancelled, 0.6),
    # misc
    "glass": (sfx.glass_break, 0.6),
    "door": (sfx.door_open, 0.5),
    "clang": (sfx.metal_clang, 0.55),
    "ui_click": (sfx.ui_click, 0.4),
    "ui_move": (sfx.ui_move, 0.3),
    "ui_confirm": (sfx.ui_confirm, 0.45),
    "ui_error": (sfx.ui_error, 0.45),
}

# key: (builder, volume) - looping beds played on dedicated channels
LOOP_REGISTRY = {
    "engine_idle": (sfx.truck_engine_loop, 0.55),
    "engine_move": (sfx.truck_moving_loop, 0.6),
    "camera_servo": (sfx.camera_servo_loop, 0.22),
    "alarm": (sfx.alarm_siren, 0.7),
    "ambient": (sfx.ambient_night_loop, 0.4),
}
