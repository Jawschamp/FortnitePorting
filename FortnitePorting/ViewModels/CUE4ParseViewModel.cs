﻿using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using CommunityToolkit.Mvvm.ComponentModel;
using CUE4Parse.Encryption.Aes;
using CUE4Parse.FileProvider;
using CUE4Parse.MappingsProvider;
using CUE4Parse.UE4.AssetRegistry;
using CUE4Parse.UE4.AssetRegistry.Objects;
using CUE4Parse.UE4.Assets.Objects;
using CUE4Parse.UE4.Assets.Utils;
using CUE4Parse.UE4.Objects.Core.Math;
using CUE4Parse.UE4.Objects.Core.Misc;
using CUE4Parse.UE4.Versions;
using FortnitePorting.AppUtils;
using FortnitePorting.Services;
using FortnitePorting.Services.Endpoints.Models;
using FortnitePorting.Views.Extensions;

namespace FortnitePorting.ViewModels;

public class CUE4ParseViewModel : ObservableObject
{
    public readonly DefaultFileProvider Provider;

    public List<FAssetData> AssetDataBuffers = new();
    
    public RarityCollection[] RarityData = new RarityCollection[8];

    public CUE4ParseViewModel(string directory)
    {
        Provider = new DefaultFileProvider(directory, SearchOption.TopDirectoryOnly, isCaseInsensitive: true, new VersionContainer(EGame.GAME_UE5_1));
    }
    
    public async Task Initialize()
    {
        Provider.Initialize();
        await InitializeKeys();
        await InitializeMappings();
        if (Provider.MappingsContainer is null)
        {
            AppLog.Warning("Failed to load mappings, issues may occur");
        }
        
        Provider.LoadLocalization(AppSettings.Current.Language);
        Provider.LoadVirtualPaths();

        var assetRegistries = Provider.Files.Where(x =>
            x.Key.Contains("AssetRegistry", StringComparison.OrdinalIgnoreCase)).ToList();

        assetRegistries.MoveToEnd(x => x.Value.Name.Equals("AssetRegistry.bin")); // i want encrypted cosmetics to be at the top :)))
        foreach (var (_, file) in assetRegistries)
        {
            await LoadAssetRegistry(file);
        }
        
        var rarityData = await Provider.LoadObjectAsync("FortniteGame/Content/Balance/RarityData.RarityData");
        for (var i = 0; i < 8; i++)
        {
            RarityData[i] = rarityData.GetByIndex<RarityCollection>(i);
        }
        
    }

    private async Task InitializeKeys()
    {
        var keyResponse = await EndpointService.FortniteCentral.GetKeysAsync();
        if (keyResponse is not null) AppSettings.Current.AesResponse = keyResponse;
        keyResponse ??= AppSettings.Current.AesResponse;
        
        await Provider.SubmitKeyAsync(Globals.ZERO_GUID, new FAesKey(keyResponse.MainKey));
        foreach (var dynamicKey in keyResponse.DynamicKeys)
        {
            await Provider.SubmitKeyAsync(new FGuid(dynamicKey.GUID), new FAesKey(dynamicKey.Key));
        }
    }

    private async Task InitializeMappings()
    {
        if (await TryDownloadMappings()) return;
        
        LoadLocalMappings();
    }

    private async Task<bool> TryDownloadMappings()
    {
        var mappingsResponse = await EndpointService.FortniteCentral.GetMappingsAsync();
        if (mappingsResponse is null) return false;
        if (mappingsResponse.Length <= 0) return false;
        
        var mappings = mappingsResponse.FirstOrDefault(x => x.Meta.CompressionMethod.Equals("Oodle", StringComparison.OrdinalIgnoreCase));
        if (mappings is null) return false;
            
        var mappingsFilePath = Path.Combine(App.DataFolder.FullName, mappings.Filename);
        if (File.Exists(mappingsFilePath)) return false;
            
        await EndpointService.DownloadFileAsync(mappings.URL, mappingsFilePath);
        Provider.MappingsContainer = new FileUsmapTypeMappingsProvider(mappingsFilePath);

        return true;
    }

    private void LoadLocalMappings()
    {
        var usmapFiles = App.DataFolder.GetFiles("*.usmap");
        if (usmapFiles.Length <= 0) return;
            
        var latestUsmap = usmapFiles.MaxBy(x => x.LastWriteTime);
        if (latestUsmap is null) return;

        Provider.MappingsContainer = new FileUsmapTypeMappingsProvider(latestUsmap.FullName);
    }

    private async Task LoadAssetRegistry(GameFile file)
    {
        var assetArchive = await file.TryCreateReaderAsync();
        if (assetArchive is null) return;
                
        var assetRegistry = new FAssetRegistryState(assetArchive);
        AssetDataBuffers.AddRange(assetRegistry.PreallocatedAssetDataBuffers);
    }
}

[StructFallback]
public class RarityCollection
{
    public FLinearColor Color1;
    public FLinearColor Color2;
    public FLinearColor Color3;
    public FLinearColor Color4;
    public FLinearColor Color5;
    public float Radius;
    public float Falloff;
    public float Brightness;
    public float Roughness;
    
    public RarityCollection(FStructFallback fallback)
    {
        Color1 = fallback.GetOrDefault<FLinearColor>(nameof(Color1));
        Color2 = fallback.GetOrDefault<FLinearColor>(nameof(Color2));
        Color3 = fallback.GetOrDefault<FLinearColor>(nameof(Color3));
        Color4 = fallback.GetOrDefault<FLinearColor>(nameof(Color4));
        Color5 = fallback.GetOrDefault<FLinearColor>(nameof(Color5));
        
        Radius = fallback.GetOrDefault<float>(nameof(Radius));
        Falloff = fallback.GetOrDefault<float>(nameof(Falloff));
        Brightness = fallback.GetOrDefault<float>(nameof(Brightness));
        Roughness = fallback.GetOrDefault<float>(nameof(Roughness));
    }

}