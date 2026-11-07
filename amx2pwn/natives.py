"""Native function databases: SA-MP / open.mp natives and callbacks, and Pawn core natives."""


from .omp_natives import CALLBACKS, NATIVES

# SA-MP / open.mp signatures come from omp_natives.py, which tools/gen_natives.py
# generates from the open.mp includes. Argument letters:
#   i=value f=Float s=array/string r=&ref fr=&Float:ref m=variadic(...)
#   p=player id v=vehicle id o=object id


# Old SA-MP callbacks and NPC-script (a_npc.inc) API that open.mp no longer
# declares, but old scripts still use. Same format as omp_natives.NATIVES.
LEGACY_NATIVES = """
SendChat s - msg
SendCommand s - commandtext
GetMyPos fr,fr,fr - x,y,z
SetMyPos f,f,f - x,y,z
GetMyFacingAngle fr - angle
SetMyFacingAngle f - angle
GetDistanceFromMeToPoint f,f,f,fr - x,y,z,distance
GetPlayerArmedWeapon p - playerid
StartRecordingPlayback i,s - playbacktype,recordname
StopRecordingPlayback - - -
PauseRecordingPlayback - - -
ResumeRecordingPlayback - - -
"""

LEGACY_CALLBACKS = {
    # SA-MP 0.2
    "OnPlayerPrivmsg": ["playerid", "receiverid", "text[]"],
    "OnPlayerTeamPrivmsg": ["playerid", "text[]"],
    "OnPlayerInfoChange": ["playerid"],
    # NPC scripts
    "OnNPCModeInit": [],
    "OnNPCModeExit": [],
    "OnNPCConnect": ["myplayerid"],
    "OnNPCDisconnect": ["reason[]"],
    "OnNPCEnterVehicle": ["vehicleid", "seatid"],
    "OnNPCExitVehicle": [],
    "OnClientMessage": ["color", "text[]"],
    "OnRecordingPlaybackEnd": [],
}


def load_samp_db():
    """-> (natives, callbacks, argnames)

    natives:   name -> (argument letters, return letter "f" or "")
    callbacks: name -> parameter list such as ["playerid", "Float:x", "text[]"]
    argnames:  native name -> parameter names from the includes
    """
    nat, names = {}, {}
    for line in (LEGACY_NATIVES.strip() + "\n" + NATIVES.strip()).splitlines():
        name, args, ret, pnames = line.split()
        nat[name] = ([] if args == "-" else args.split(","), "" if ret == "-" else ret)
        names[name] = [] if pnames == "-" else pnames.split(",")
    cb = dict(LEGACY_CALLBACKS)
    for line in CALLBACKS.strip().splitlines():
        name, args = line.split(None, 1)
        cb[name] = [] if args.strip() == "-" else args.strip().split(",")
    return nat, cb, names


# core natives (core/string/float/file) with default arguments
CORE_NATIVES = """
strlen(const string[])
strpack(dest[], const source[], maxlength=sizeof dest)
strunpack(dest[], const source[], maxlength=sizeof dest)
strcat(dest[], const source[], maxlength=sizeof dest)
strmid(dest[], const source[], start, end, maxlength=sizeof dest)
strins(string[], const substr[], pos, maxlength=sizeof string)
strdel(string[], start, end)
strcmp(const string1[], const string2[], ignorecase=false, length=cellmax)
strfind(const string[], const sub[], ignorecase=false, pos=0)
strval(const string[])
valstr(dest[], value, pack=false)
ispacked(const string[])
format(output[], len, const format[], {Float,_}:...)
print(const string[])
printf(const format[], {Float,_}:...)
tolower(c)
toupper(c)
random(max)
min(value1, value2)
max(value1, value2)
clamp(value, min=cellmin, max=cellmax)
heapspace()
funcidx(const name[])
numargs()
getarg(arg, index=0)
setarg(arg, index=0, value)
gettime(&hour=0, &minute=0, &second=0)
getdate(&year=0, &month=0, &day=0)
tickcount(&granularity=0)
fopen(const name[], filemode:mode=io_readwrite)
fclose(handle)
fwrite(handle, const string[])
fread(handle, string[], size=sizeof string, pack=false)
fputchar(handle, value, utf8=true)
fgetchar(handle, value, utf8=true)
fblockwrite(handle, const buffer[], size=sizeof buffer)
fblockread(handle, buffer[], size=sizeof buffer)
fseek(handle, position=0, seek_whence:whence=seek_start)
flength(handle)
fexist(const pattern[])
fremove(const name[])
Float:float(value)
Float:floatstr(const string[])
Float:floatmul(Float:oper1, Float:oper2)
Float:floatdiv(Float:dividend, Float:divisor)
Float:floatadd(Float:oper1, Float:oper2)
Float:floatsub(Float:oper1, Float:oper2)
Float:floatfract(Float:value)
floatround(Float:value, floatround_method:method=floatround_round)
floatcmp(Float:oper1, Float:oper2)
Float:floatsqroot(Float:value)
Float:floatpower(Float:value, Float:exponent)
Float:floatsin(Float:value, anglemode:mode=radian)
Float:floatcos(Float:value, anglemode:mode=radian)
Float:floattan(Float:value, anglemode:mode=radian)
Float:floatabs(Float:value)
"""

ENUMS = {
    "filemode": ["io_read", "io_write", "io_readwrite", "io_append"],
    "seek_whence": ["seek_start", "seek_current", "seek_end"],
    "floatround_method": ["floatround_round", "floatround_floor", "floatround_ceil",
                          "floatround_tozero", "floatround_unbiased"],
    "anglemode": ["radian", "degrees", "grades"],
}


def parse_core_natives():
    out = {}
    for line in CORE_NATIVES.strip().splitlines():
        ret = ""
        if line.startswith("Float:"):
            ret, line = "Float:", line[6:]
        name, rest = line.split("(", 1)
        ps = [x.strip() for x in rest.rstrip(")").split(",") if x.strip()]
        names, defs, kinds = [], [], []
        va = False
        for x in ps:
            if x.endswith("..."):
                va = True
                break
            dflt = None
            if "=" in x:
                x, dflt = [t.strip() for t in x.split("=", 1)]
            tag = None
            nm = x.replace("const ", "").replace("&", "").replace("[]", "")
            if ":" in nm:
                tag, nm = nm.split(":", 1)
            names.append(nm)
            kinds.append(tag)
            defs.append(dflt)
        dd = []
        for k, dflt in enumerate(defs):
            if dflt is None:
                dd.append(None)
            elif dflt.startswith("sizeof "):
                dd.append(("sz", names.index(dflt[7:])))
            elif dflt in ("false", "true"):
                dd.append(("bool", int(dflt == "true")))
            elif dflt == "cellmax":
                dd.append(("v", 0x7FFFFFFF))
            elif dflt == "cellmin":
                dd.append(("v", -0x80000000))
            elif kinds[k] in ENUMS:
                dd.append(("enum", kinds[k], ENUMS[kinds[k]].index(dflt)))
            else:
                dd.append(("v", int(dflt)))
        nreq = sum(1 for x in dd if x is None)
        out[name] = dict(decl="native %s%s(%s);" % (ret, name, rest.rstrip(")")),
                         n=len(names), nreq=nreq, va=va, defs=dd, kinds=kinds)
    return out


CORE = parse_core_natives()


# preferred parameter names for common SA-MP natives (used to name script variables;
# the argument types come from omp_natives.py)
_NATIVE_PNAMES = """
SetPlayerMapIcon: playerid iconid x y z markertype color
GetPlayerPos: playerid x y z
SetPlayerPos: playerid x y z
IsPlayerInAnyVehicle: playerid
GetPlayerVehicleID: playerid
GetVehicleZAngle: vehicleid z_angle
SetVehicleZAngle: vehicleid z_angle
GetPlayerFacingAngle: playerid ang
SetPlayerFacingAngle: playerid ang
GetVehicleModel: vehicleid
GetVehiclePos: vehicleid x y z
SetVehiclePos: vehicleid x y z
IsPlayerConnected: playerid
GetPlayerName: playerid name len
SetPlayerName: playerid name
GetPlayerIp: playerid name len
ResetPlayerMoney: playerid
GivePlayerMoney: playerid money
GetPlayerMoney: playerid
SetPlayerScore: playerid score
GetPlayerScore: playerid
TextDrawHideForPlayer: playerid text
TextDrawShowForPlayer: playerid text
TextDrawHideForAll: text
TextDrawShowForAll: text
TextDrawSetString: text string
TextDrawCreate: x y text
TextDrawDestroy: text
TextDrawLetterSize: text x y
TextDrawTextSize: text x y
TextDrawAlignment: text alignment
TextDrawColor: text color
TextDrawUseBox: text use
TextDrawBoxColor: text color
TextDrawSetShadow: text size
TextDrawSetOutline: text size
TextDrawBackgroundColor: text color
TextDrawFont: text font
TextDrawSetProportional: text set
SendClientMessage: playerid color message
SendClientMessageToAll: color message
SendPlayerMessageToAll: senderid message
SendDeathMessage: killer killee weapon
GameTextForPlayer: playerid string time style
GameTextForAll: string time style
SetPlayerSkin: playerid skinid
GetPlayerSkin: playerid
GetServerVarAsInt: varname
GetServerVarAsString: varname buffer len
GetServerVarAsBool: varname
SendRconCommand: command
SetGameModeText: string
AllowInteriorWeapons: allow
AllowAdminTeleport: allow
ShowPlayerMarkers: mode
ShowNameTags: show
EnableStuntBonusForAll: enable
SetTimer: funcname interval repeating
SetTimerEx: funcname interval repeating format
KillTimer: timerid
AddPlayerClass: modelid spawn_x spawn_y spawn_z z_angle weapon1 weapon1_ammo weapon2 weapon2_ammo weapon3 weapon3_ammo
SetSpawnInfo: playerid team skin x y z rotation weapon1 weapon1_ammo weapon2 weapon2_ammo weapon3 weapon3_ammo
AddStaticPickup: model type x y z virtualworld
CreatePickup: model type x y z virtualworld
DestroyPickup: pickup
CreateMenu: title columns x y col1width col2width
AddMenuItem: menuid column menutext
SetMenuColumnHeader: menuid column columnheader
IsValidMenu: menuid
ShowMenuForPlayer: menuid playerid
HideMenuForPlayer: menuid playerid
DestroyMenu: menuid
GetPlayerMenu: playerid
CreateObject: modelid x y z rx ry rz drawdistance
CreatePlayerObject: playerid modelid x y z rx ry rz drawdistance
MoveObject: objectid x y z speed
DestroyObject: objectid
AddStaticVehicle: modelid spawn_x spawn_y spawn_z z_angle color1 color2
AddStaticVehicleEx: modelid spawn_x spawn_y spawn_z z_angle color1 color2 respawn_delay
CreateVehicle: vehicletype x y z rotation color1 color2 respawn_delay
DestroyVehicle: vehicleid
AddVehicleComponent: vehicleid componentid
LinkVehicleToInterior: vehicleid interiorid
ChangeVehicleColor: vehicleid color1 color2
SetVehicleHealth: vehicleid health
GetVehicleHealth: vehicleid health
SetVehicleToRespawn: vehicleid
SetVehicleParamsForPlayer: vehicleid playerid objective doorslocked
IsTrailerAttachedToVehicle: vehicleid
DetachTrailerFromVehicle: vehicleid
AttachTrailerToVehicle: trailerid vehicleid
SetVehicleVirtualWorld: vehicleid worldid
SetVehicleNumberPlate: vehicleid numberplate
Ban: playerid
BanEx: playerid reason
Kick: playerid
SetPlayerColor: playerid color
GetPlayerColor: playerid
PlayerPlaySound: playerid soundid x y z
SetPlayerCameraPos: playerid x y z
SetPlayerCameraLookAt: playerid x y z
SetCameraBehindPlayer: playerid
GangZoneCreate: minx miny maxx maxy
GangZoneDestroy: zone
GangZoneShowForPlayer: playerid zone color
GangZoneHideForPlayer: playerid zone
GangZoneShowForAll: zone color
GangZoneHideForAll: zone
GangZoneFlashForAll: zone flashcolor
GangZoneStopFlashForAll: zone
ResetPlayerWeapons: playerid
GivePlayerWeapon: playerid weaponid ammo
GetPlayerWeapon: playerid
GetPlayerWeaponData: playerid slot weapons ammo
SetPlayerInterior: playerid interiorid
GetPlayerInterior: playerid
SetPlayerVirtualWorld: playerid worldid
GetPlayerVirtualWorld: playerid
SetPlayerCheckpoint: playerid x y z size
DisablePlayerCheckpoint: playerid
IsPlayerInCheckpoint: playerid
SetPlayerRaceCheckpoint: playerid type x y z nextx nexty nextz size
DisablePlayerRaceCheckpoint: playerid
IsPlayerInRaceCheckpoint: playerid
GetPlayerWantedLevel: playerid
SetPlayerWantedLevel: playerid level
GetPlayerState: playerid
SetPlayerSpecialAction: playerid actionid
ApplyAnimation: playerid animlib animname fDelta loop lockx locky freeze time forcesync
SetPlayerHealth: playerid health
GetPlayerHealth: playerid health
SetPlayerArmour: playerid armour
GetPlayerArmour: playerid armour
TogglePlayerControllable: playerid toggle
TogglePlayerSpectating: playerid toggle
PlayerSpectatePlayer: playerid targetplayerid mode
PlayerSpectateVehicle: playerid targetvehicleid mode
PutPlayerInVehicle: playerid vehicleid seatid
RemovePlayerFromVehicle: playerid
IsPlayerInVehicle: playerid vehicleid
ShowPlayerNameTagForPlayer: playerid showplayerid show
CreateExplosion: x y z type radius
IsPlayerAdmin: playerid
SetWeather: weatherid
SetWorldTime: hour
SetPlayerTime: playerid hour minute
GetPlayerPing: playerid
GetPlayerKeys: playerid keys updown leftright
SetPlayerTeam: playerid teamid
GetPlayerTeam: playerid
SpawnPlayer: playerid
SetPlayerAmmo: playerid weaponslot ammo
SetGravity: gravity
SetNameTagDrawDistance: distance
EnableTirePopping: enable
SetDeathDropAmount: amount
ShowPlayerDialog: playerid dialogid style caption info button1 button2
"""

NATIVE_PNAMES = {}

for _l in _NATIVE_PNAMES.strip().splitlines():
    _n, _a = _l.split(":", 1)
    NATIVE_PNAMES[_n.strip()] = _a.split()
