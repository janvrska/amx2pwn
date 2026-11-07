"""Knowledge used for naming: well-known library functions and typical variable names."""


# Signatures of well-known library functions (dini, dudb, dutils and commonly copied stocks).
# Each entry: (name, parameter names, conditions). Conditions:
#   np       number of parameters
#   nat      natives the function must call
#   natonly  the only natives it may call (basic float natives are always allowed)
#   str      string literals it must contain
#   const    constants it must contain
#   calls    already recognised functions it must call
#   nocalls  calls no other script function
#   ret_arr  returns an array (True/False)
#   nocreate must not create files (used to tell udb_CheckLogin from udb_Create)
# To support another library, add its functions here.
LIBSIGS = [
    # --- dudb / dini / dutils (DracoBlue)
    ("udb_hash", ["buf"], dict(np=1, const=[65521])),
    ("udb_encode", ["nickname"], dict(np=1, str=["_00", "_01"])),
    ("dini_Set", ["filename", "key", "value"], dict(np=3, str=["%s.part"])),
    ("dini_Unset", ["filename", "key"], dict(np=2, str=["%s.part"])),
    ("StripNewLine", ["string"], dict(nat=["strlen"], np=1, natonly=["strlen"], const=[10, 13], nocalls=True, ret_arr=False)),
    ("fcopytextfile", ["oldname", "newname"], dict(np=2, nat=["fread", "fwrite"], calls=["StripNewLine"])),
    ("fcopy", ["oldname", "newname"], dict(np=2, nat=["fblockread", "fblockwrite"])),
    ("frename", ["oldname", "newname"], dict(np=2, nat=["fremove"], calls=["fcopy"])),
    ("ret_memcpy", ["source", "index", "numbytes"], dict(nat=["strlen"], np=3, ret_arr=True, natonly=["strlen"], nocalls=True)),
    ("strlower", ["txt"], dict(np=1, ret_arr=True, nat=["tolower"], natonly=["strlen", "tolower"])),
    ("strupper", ["txt"], dict(np=1, ret_arr=True, nat=["toupper"], natonly=["strlen", "toupper"])),
    ("equal", ["str1", "str2", "ignorecase"], dict(np=3, nat=["strcmp", "strlen"], natonly=["strcmp", "strlen"], nocalls=True)),
    ("strreplace", ["trg", "newstr", "src"], dict(np=3, nat=["strfind", "strcat"], calls=["ret_memcpy"])),
    ("set", ["dest", "source"], dict(nat=["strlen"], np=2, natonly=["strlen"], nocalls=True, ret_arr=False)),
    ("fixchars", ["txt"], dict(nat=["strlen"], np=1, natonly=["strlen"], const=[256], nocalls=True, ret_arr=False)),
    ("dini_PRIVATE_ExtractKey", ["line"], dict(np=1, ret_arr=True, str=["="], calls=["strlower"])),
    ("dini_PRIVATE_ExtractValue", ["line"], dict(np=1, ret_arr=True, str=["="], calls=["ret_memcpy"])),
    ("ExtractValue", ["line"], dict(np=1, ret_arr=True, str=["="], nat=["strmid", "strfind"])),
    ("dini_Exists", ["filename"], dict(np=1, nat=["fexist"], natonly=["fexist"], nocalls=True)),
    ("dini_Create", ["filename"], dict(np=1, nat=["fexist", "fopen", "fclose"], natonly=["fexist", "fopen", "fclose"], nocalls=True)),
    ("dini_Remove", ["filename"], dict(np=1, nat=["fremove"], natonly=["fexist", "fremove"], nocalls=True)),
    ("dini_Get", ["filename", "key"], dict(np=2, ret_arr=True, nat=["fopen", "fread"], calls=["dini_PRIVATE_ExtractKey"])),
    ("dini_Isset", ["filename", "key"], dict(np=2, ret_arr=False, nat=["fopen", "fread"], calls=["dini_PRIVATE_ExtractKey"])),
    ("dini_Int", ["filename", "key"], dict(np=2, nat=["strval"], calls=["dini_Get"])),
    ("dini_Float", ["filename", "key"], dict(np=2, nat=["floatstr"], calls=["dini_Get"])),
    ("dini_IntSet", ["filename", "key", "value"], dict(np=3, str=["%d"], calls=["dini_Set"])),
    ("dini_FloatSet", ["filename", "key", "value"], dict(np=3, str=["%f"], calls=["dini_Set"])),
    ("udb_Exists", ["nickname"], dict(np=1, str=["%s.dudb.sav"], nat=["fexist"])),
    ("udb_UserSetInt", ["nickname", "key", "value"], dict(np=3, str=["%s.dudb.sav"], calls=["dini_IntSet"])),
    ("udb_UserSetFloat", ["nickname", "key", "value"], dict(np=3, str=["%s.dudb.sav"], calls=["dini_FloatSet"])),
    ("udb_UserSet", ["nickname", "key", "value"], dict(np=3, str=["%s.dudb.sav"], calls=["dini_Set"])),
    ("udb_UserInt", ["nickname", "key"], dict(np=2, str=["%s.dudb.sav"], calls=["dini_Int"])),
    ("udb_UserFloat", ["nickname", "key"], dict(np=2, str=["%s.dudb.sav"], calls=["dini_Float"])),
    ("udb_User", ["nickname", "key"], dict(np=2, str=["%s.dudb.sav"], calls=["dini_Get"], ret_arr=True)),
    ("udb_CheckLogin", ["nickname", "pwd"], dict(np=2, str=["password_hash"], calls=["udb_hash"], nocreate=True)),
    ("udb_Create", ["nickname", "pwd"], dict(np=2, str=["password_hash"], calls=["dini_Create"])),
    ("udb_Remove", ["nickname"], dict(np=1, str=["%s.dudb.sav"], calls=["dini_Remove"])),
    # --- functions commonly copied around the SA-MP community
    ("strtok", ["string", "index"], dict(nat=["strlen"], np=2, ret_arr=True, natonly=["strlen"], const=[32], nocalls=True)),
    ("IsNumeric", ["string"], dict(nat=["strlen"], np=1, ret_arr=False, natonly=["strlen"], const=[48, 57], nocalls=True)),
    ("FindChar", ["c", "string", "start"], dict(nat=["strlen"], np=3, ret_arr=False, natonly=["strlen"], const=[-1], nocalls=True)),
    ("PlayerName", ["playerid"], dict(np=1, ret_arr=True, nat=["GetPlayerName"], natonly=["GetPlayerName", "IsPlayerConnected"])),
    ("GetPlayerIDFromName", ["name"], dict(np=1, ret_arr=False, nat=["GetPlayerName", "strcmp"],
                                            natonly=["GetPlayerName", "strcmp", "IsPlayerConnected", "strlen"])),
    ("GetXYInFrontOfPlayer", ["playerid", "x", "y", "distance"], dict(np=4, nat=["GetPlayerPos", "floatsin", "floatcos"])),
    ("GetDistanceBetweenPlayers", ["playerid1", "playerid2"], dict(np=2, nat=["GetPlayerPos", "floatsqroot"],
                                                                   natonly=["GetPlayerPos", "floatsqroot", "floatpower", "floatround", "IsPlayerConnected"])),
    ("GetDistanceToPoint", ["playerid", "x", "y", "z"], dict(np=4, nat=["GetPlayerPos", "floatsqroot"],
                                                             natonly=["GetPlayerPos", "floatsqroot", "floatpower", "floatround", "IsPlayerConnected"])),
    ("IsPlayerNearPoint", ["playerid", "x", "y", "z", "radius"], dict(np=5, calls=["GetDistanceToPoint"], natonly=[])),
    ("IsPlayerInArea", ["playerid", "minx", "maxx", "miny", "maxy"], dict(np=5, nat=["GetPlayerPos"], natonly=["GetPlayerPos"], nocalls=True)),
]


# local variable names by where they are passed (output arguments)
OUTNAMES = {
    "GetPlayerPos": {1: "x", 2: "y", 3: "z"}, "GetVehiclePos": {1: "x", 2: "y", 3: "z"},
    "GetObjectPos": {1: "x", 2: "y", 3: "z"}, "GetPlayerFacingAngle": {1: "angle"},
    "GetVehicleZAngle": {1: "angle"}, "GetPlayerHealth": {1: "health"}, "GetPlayerArmour": {1: "armour"},
    "GetVehicleHealth": {1: "health"}, "GetPlayerName": {1: "name"}, "GetPlayerIp": {1: "ip"},
    "format": {0: "string"}, "gettime": {0: "hour", 1: "minute", 2: "second"},
    "getdate": {0: "year", 1: "month", 2: "day"}, "GetPlayerWeaponData": {2: "weapon", 3: "ammo"},
    "GetServerVarAsString": {1: "value"}, "fread": {1: "line"},
    "GetPlayerKeys": {1: "keys", 2: "updown", 3: "leftright"},
    "GetXYInFrontOfPlayer": {1: "x", 2: "y"},
}


# ... and by what is assigned to them
RETNAMES = {
    "GetPlayerVehicleID": "vehicleid", "GetVehicleModel": "model", "GetPlayerMoney": "money",
    "GetPlayerState": "pstate", "GetPlayerInterior": "interior", "GetPlayerWeapon": "weapon",
    "GetPlayerSkin": "skin", "GetPlayerScore": "score", "GetPlayerPing": "ping",
    "GetPlayerWantedLevel": "wanted", "GetPlayerColor": "color", "GetPlayerMenu": "menu",
    "GetPlayerVirtualWorld": "world", "GetPlayerTeam": "team", "strlen": "len", "fopen": "file",
    "strval": "value", "CreateVehicle": "vehicleid", "AddStaticVehicle": "vehicleid",
    "CreateObject": "objectid", "CreatePickup": "pickupid", "TextDrawCreate": "textdraw",
    "strfind": "pos", "SetTimer": "timer", "SetTimerEx": "timer", "random": "rand",
    "strtok": "tmp", "PlayerName": "name", "dini_Get": "value", "dini_Int": "value",
    "udb_UserInt": "value", "udb_User": "value", "GetDistanceBetweenPlayers": "distance",
    "GetDistanceToPoint": "distance", "GetPlayerIDFromName": "id", "floatsqroot": "distance",
}


# global variable names by what is assigned to them
GLOBNAMES = {
    "SetTimer": "timer", "SetTimerEx": "timer", "TextDrawCreate": "textdraw", "CreateMenu": "menu",
    "CreateVehicle": "vehicle", "AddStaticVehicle": "vehicle", "AddStaticVehicleEx": "vehicle",
    "CreatePickup": "pickup", "CreateObject": "object", "GangZoneCreate": "gangzone", "fopen": "file",
    "CreatePlayerObject": "pobject",
}


# names that are too generic to be used as variable names
GENERIC_PNAMES = {"string", "text", "x", "y", "z", "type", "mode", "set", "use", "show", "toggle",
                  "allow", "enable", "size", "len", "name", "format", "message", "buffer", "varname"}

PAWN_KEYWORDS = {"assert", "break", "case", "char", "const", "continue", "default", "defined", "do",
                 "else", "enum", "exit", "for", "forward", "goto", "if", "native", "new", "operator",
                 "public", "return", "sizeof", "sleep", "state", "static", "stock", "switch", "tagof",
                 "while", "true", "false", "EOS", "cellmax", "cellmin", "cellbits", "charbits"}

FLOAT_BASIC = {"float", "floatadd", "floatsub", "floatmul", "floatdiv", "floatcmp", "floatabs"}
