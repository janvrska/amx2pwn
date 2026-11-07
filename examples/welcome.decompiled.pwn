// ==========================================================
//  Decompiled from: welcome.amx   (amx2pwn)
//  Variable and function names without debug info are generated.
//  Compile without a_samp/float.inc - natives and float operators are declared below.
// ==========================================================

#pragma rational Float
#pragma tabsize 0
#pragma dynamic 4096

// ---------------------------------------------------------- natives
native IsPlayerConnected(playerid);
native GetPlayerName(playerid, const name[], len);
native format(output[], len, const format[], {Float,_}:...);
native SendClientMessage(playerid, color, const message[]);

// ---------------------------------------------------------- global variables
new g_0[50];

// ---------------------------------------------------------- forwards
forward OnPlayerConnect(playerid);

stock func_8()
{
    new var0;
    for (new i; i < 50; i++)
    {
        if (IsPlayerConnected(i))
        {
            var0++;
        }
    }
    return var0;
}

public OnPlayerConnect(playerid)
{
    new name[24];
    new string[128];
    GetPlayerName(playerid, name, sizeof(name));
    g_0[playerid]++;
    format(string, sizeof(string), "Welcome, %s! Players online: %d", name, func_8());
    SendClientMessage(playerid, 0x33CCFFFF, string);
    if (g_0[playerid] > 1)
    {
        SendClientMessage(playerid, -1, "Welcome back!");
    }
    return 1;
}

main()
{
}

