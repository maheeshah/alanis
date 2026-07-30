﻿using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text.Json;
using Wabtec.TrackStore;
using System.Text.Json.Serialization;


namespace subdivs;

public class Program
{
    private class ParsedSegment
    {
            
        [JsonPropertyName("scac")]
        public string SCAC { get; set; } = string.Empty;

        [JsonPropertyName("subdivision_id")]
        public uint Subdivision { get; set; }

        [JsonPropertyName("track_name")]
        public string Track { get; set; } = string.Empty;

        [JsonPropertyName("start_mp")]
        public double StartMP { get; set; }

        [JsonPropertyName("end_mp")]
        public double EndMP { get; set; }

        [JsonPropertyName("start_prefix")]
        public string StartPrefix { get; set; } = string.Empty;

        [JsonPropertyName("start_suffix")]
        public string StartSuffix { get; set; } = string.Empty;

        [JsonPropertyName("end_prefix")]
        public string EndPrefix { get; set; } = string.Empty;

        [JsonPropertyName("end_suffix")]
        public string EndSuffix { get; set; } = string.Empty;

        [JsonPropertyName("start_lat")]
        public double? StartLat { get; set; }

        [JsonPropertyName("start_lon")]
        public double? StartLon { get; set; }

        [JsonPropertyName("end_lat")]
        public double? EndLat { get; set; }

        [JsonPropertyName("end_lon")]
        public double? EndLon { get; set; }

        [JsonPropertyName("start_location")]
        public string? StartLocation { get; set; }

        [JsonPropertyName("end_location")]
        public string? EndLocation { get; set; }   
    }

    static void Main(string[] args)
    {
        string trackFolderPath = @"C:\Users\mahee.shah\Desktop\TrackFiles7-22-24Update";
        string parsedMessagesPath = @"C:\Users\mahee.shah\Desktop\trackproject\subdivs\Bulletin Search Results - Actual\location_extraction_bnsf.jsonl";
        string outputPath = @"C:\Users\mahee.shah\Desktop\trackproject\subdivs\matched_tracks_bnsf.json";

        Console.WriteLine("Starting track matcher...");
        //Does the .opk folder exist?
        if (!Directory.Exists(trackFolderPath))
        {
            Console.WriteLine($"Track folder not found: {trackFolderPath}");
            return;
        }
        //Does the input JSONL file exist?
        if (!File.Exists(parsedMessagesPath))
        {
            Console.WriteLine($"Input file not found: {parsedMessagesPath}");
            return;
        }

        Console.WriteLine("Building OPK index...");
        //("CSXT", 318) -> "CSXT.00318.16.opk"
        var opkIndex = BuildOpkIndex(trackFolderPath);

        //load OPK files as needed and cache them in memory
        var loadedTrackFiles =
            new Dictionary<(string SCAC, uint Subdivision), TrackFile>();
        //clear the output file if it already exists
        File.WriteAllText(outputPath, string.Empty);
        //create a StreamWriter to write the output JSONL file continuously as we process each segment
        using var writer = new StreamWriter(outputPath);

        int processedCount = 0;

        foreach (var seg in LoadParsedSegmentsJsonl(parsedMessagesPath))
        {
            processedCount++;

            string scac = NormalizeScac(seg.SCAC);
            //create a key to look up the OPK file for this SCAC and Subdivision
            var key = (scac, seg.Subdivision);

            //Do we have an OPK for this railroad and subdivision? If not, skip this segment.
            if (!opkIndex.TryGetValue(key, out var opkPath))
            {
                continue;
            }

            //Have we already loaded this OPK? If not, load it and cache it in memory.
            if (!loadedTrackFiles.TryGetValue(key, out var trackFile))
            {
                try
                {
                    trackFile = TrackFile.ReadWabtecTrackFile(opkPath);
                    loadedTrackFiles[key] = trackFile;
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"Failed to load {opkPath}: {ex.Message}");
                    continue;
                }
            }

            //Finds matching track name
            //Finds matching start block
            //Finds matching end block
            //Reads coordinates
            //Stores coordinates in seg.StartLat, seg.StartLon, seg.EndLat, seg.EndLon
            MatchSegmentToTrackFile(seg, trackFile);

            // Write result
            writer.WriteLine(JsonSerializer.Serialize(seg));

            if (processedCount % 1000 == 0)
            {
                writer.Flush();
                Console.WriteLine($"Processed {processedCount} rows...");
            }
        }

        writer.Flush();

        Console.WriteLine($"Done. Processed {processedCount} rows.");
        Console.WriteLine($"Loaded {loadedTrackFiles.Count} OPK files.");
        Console.WriteLine($"Output: {outputPath}");
    }

       private static IEnumerable<ParsedSegment> LoadParsedSegmentsJsonl(string path)
        {
            var options = new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true
            };

            int lineNumber = 0;

            foreach (string line in File.ReadLines(path))
            {
                lineNumber++;

                if (string.IsNullOrWhiteSpace(line))
                {
                    continue;
                }

                ParsedSegment? segment = null;

                try
                {
                    segment = JsonSerializer.Deserialize<ParsedSegment>(line, options);
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"Invalid JSON on line {lineNumber}: {ex.Message}");
                }

                if (segment != null)
                {
                    yield return segment;
                }
            }
        }

     private static Dictionary<(string SCAC, uint Subdivision), string> BuildOpkIndex(string trackFolderPath)
    {
        //stores: ("CSXT", 318) -> "C:\\Tracks\\CSXT.00318.16.opk"
        var opkIndex = new Dictionary<(string SCAC, uint Subdivision), string>();
        //find all .opk files in the track folder and its subfolders
        foreach (var filePath in Directory.EnumerateFiles(
            trackFolderPath,
            "*.opk",
            SearchOption.AllDirectories))
        {
            //remove .opk extension and get the file name
            string fileName = Path.GetFileNameWithoutExtension(filePath);
            //split on period to get SCAC and subdivision
            string[] parts = fileName.Split('.');
            //skip files that don't have at least two parts (SCAC and subdivision)
            if (parts.Length < 2)
            {
                continue;
            }
            //normalize scac for example, "CSXT" -> "CSXT"
            string scac = NormalizeScac(parts[0]);
            //get subdiv
            //converts "00318" to 318
            if (!uint.TryParse(parts[1], out uint subdivision))
            {
                continue;
            }
            //create a key for the dictionary
            //stores: ("CSXT", 318) -> path
            //if duplicate, keep the first one found and ignore the rest
            var key = (scac, subdivision);

            if (!opkIndex.ContainsKey(key))
            {
                opkIndex[key] = filePath;
            }
        }

        return opkIndex;
    }

        private static void MatchSegmentToTrackFile(
        ParsedSegment seg,
        TrackFile trackFile)
    {
        //find all blocks in the track file that match the track name of the segment
        string trackName = NormalizeText(seg.Track);

        var matchingBlocks = trackFile.Blocks
            .Where(block =>
                NormalizeText(trackFile.GetBlockTrackName(block)) == trackName)
            .ToList();

        if (!matchingBlocks.Any())
        {
            return;
        }
        //matches: track name, start prefix, start suffix, and start milepost
        var startBlock = matchingBlocks
            .Where(block =>
                NormalizeText(block.Prefix) == NormalizeText(seg.StartPrefix) &&
                NormalizeText(block.Suffix) == NormalizeText(seg.StartSuffix))
            .FirstOrDefault(block =>
                MilepostIsInsideBlock(
                    seg.StartMP,
                    block.StartMilepost,
                    block.EndMilepost));

        
        if (startBlock != null)
        {
            var (lat, lon) = ReadGeo(startBlock.StartGeo);

            if (!lat.HasValue || !lon.HasValue)
            {
                (lat, lon) = ReadGeo(startBlock.CenterGeo);
            }

            seg.StartLat = lat;
            seg.StartLon = lon;
        }

        //finds the end block that matches the segment's end prefix, end suffix, and end milepost
        var endBlock = matchingBlocks
            .Where(block =>
                NormalizeText(block.Prefix) == NormalizeText(seg.EndPrefix) &&
                NormalizeText(block.Suffix) == NormalizeText(seg.EndSuffix))
            .FirstOrDefault(block =>
                MilepostIsInsideBlock(
                    seg.EndMP,
                    block.StartMilepost,
                    block.EndMilepost));

        
        if (endBlock != null)
        {
            var (lat, lon) = ReadGeo(
                GetPropertyValue(endBlock, "EndGeo"));

            if (!lat.HasValue || !lon.HasValue)
            {
                (lat, lon) = ReadGeo(endBlock.CenterGeo);
            }

            seg.EndLat = lat;
            seg.EndLon = lon;
        }

    }

       private static bool MilepostIsInsideBlock(
            double milepost,
            double startMP,
            double endMP)
        {
            //check if the milepost is within the range of startMP and endMP, regardless of their order
            return milepost >= Math.Min(startMP, endMP) &&
                milepost <= Math.Max(startMP, endMP);
        }

        private static string NormalizeScac(string scac)
        {
            scac = NormalizeText(scac);
            //normalize known variations of SCAC codes to match OPK filenames
            return scac switch
            {
                "CSX" => "CSXT",
                "UPRR" => "UP",
                "UNIONPACIFIC" => "UP",
                "BNSFRAILWAY" => "BNSF",
                _ => scac
            };
        }
        private static string NormalizeText(string? value)
        {
            return (value ?? string.Empty).Trim().ToUpperInvariant();
        }

        private static (double? Lat, double? Lon) ReadGeo(object? geo)
        {
            if (geo == null)
            {
                return (null, null);
            }
            //Use reflection to get the Latitude and Longitude properties from the GeoPoint object.
            var lat = ConvertToNullableDouble(
                geo.GetType()
                .GetProperty("Latitude", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance)
                ?.GetValue(geo));
            //Use reflection to get the Longitude property from the GeoPoint object.
            var lon = ConvertToNullableDouble(
                geo.GetType()
                .GetProperty("Longitude", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance)
                ?.GetValue(geo));

            return (lat, lon);
        }

        private static object? GetPropertyValue(
            object instance,
            string propertyName)

        {
            //GetValue uses reflection to get the value of a property from an object. It can access public and non-public instance properties.
            //reflection means that the code can inspect and interact with the metadata of types at runtime, allowing it to access properties, methods, and fields dynamically.
            var prop = instance.GetType().GetProperty(
                propertyName,
                BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance
            );
            //If the property is found, GetValue retrieves its value from the instance. If the property is not found, it returns null.
            return prop?.GetValue(instance);
        }

        private static double? ConvertToNullableDouble(object? value)
        {
            //null check
            if (value == null)
            {
                return null;
            }
            //check if value is already a double, float, or decimal and convert accordingly
            if (value is double d) return d;
            if (value is float f) return f;
            if (value is decimal m) return (double)m;

            if (double.TryParse(
                value.ToString(),
                NumberStyles.Float,
                CultureInfo.InvariantCulture,
                out double result))
            {
                return result;
            }

            return null;
        }

    }
