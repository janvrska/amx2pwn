// Small filterscript-style example used in the README.
// Compiled without -d, so the .amx has no debug info (no names).

native SendClientMessage(playerid, color, const message[]);
native GetPlayerName(playerid, const name[], len);
native IsPlayerConnected(playerid);
native format(output[], len, const format[], {Float,_}:...);

#define MAX_PLAYERS 50

new gVisits[MAX_PLAYERS];

stock CountOnline()
{
    new count = 0;
    for (new i = 0; i < MAX_PLAYERS; i++)
    {
        if (IsPlayerConnected(i))
            count++;
    }
    return count;
}

public OnPlayerConnect(playerid)
{
    new name[24], msg[128];
    GetPlayerName(playerid, name, sizeof name);
    gVisits[playerid]++;
    format(msg, sizeof msg, "Welcome, %s! Players online: %d", name, CountOnline());
    SendClientMessage(playerid, 0x33CCFFFF, msg);
    if (gVisits[playerid] > 1)
        SendClientMessage(playerid, 0xFFFFFFFF, "Welcome back!");
    return 1;
}

main()
{
}
