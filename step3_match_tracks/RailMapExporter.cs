using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using Wabtec.TrackStore;

namespace TrackStoreGui
{
    public static class RailMapExporter
    {
       public static void Export(TrackStore trackStore, string outputPath)
        {
            
            System.Windows.MessageBox.Show(outputPath);

            System.Windows.MessageBox.Show("Export method reached");
            var trackFiles = new List<object>();

            foreach (var trackFile in trackStore.TrackFiles)
            {
                var tracks = new List<object>();
                var signals = new List<object>();
                var switches = new List<object>();
                var crossings = new List<object>();
                var signages = new List<object>();
                var mileposts = new List<object>();
                var milepostMeasurements = new List<object>();


        foreach (var block in trackFile.Blocks)
        {
            var points = new List<object>();

            foreach (var heading in block.Headings)
            {
                points.Add(new
                {
                    lat = heading.GeoPoint.Latitude,
                    lon = heading.GeoPoint.Longitude,
                    offset = heading.Offset
                });
            }

            tracks.Add(new
            {
                blockId = block.BlockId,
                points = points
            });

            // Signals
            if (block.Signals != null)
            {
                foreach (var signal in block.Signals)
                {
                    signals.Add(new
                    {
                        id = signal.SignalId,
                        name = signal.SignalName,
                        lat = signal.GeoPoint.Latitude,
                        lon = signal.GeoPoint.Longitude
                    });
                }
            }

            // Highway Crossings
            if (block.HighwayCrossings != null)
            {
                foreach (var crossing in block.HighwayCrossings)
                {
                    crossings.Add(new
                    {
                        id = crossing.CrossingId,
                        name = crossing.CrossingName,
                        lat = crossing.GeoPoint.Latitude,
                        lon = crossing.GeoPoint.Longitude
                    });
                }
            }

            // Signages
            if (block.Signages != null)
            {
                foreach (var signage in block.Signages)
                {
                    signages.Add(new
                    {
                        text = signage.SignText,
                        lat = signage.GeoPoint.Latitude,
                        lon = signage.GeoPoint.Longitude
                    });
                }
            }

            // Milepost Markers
            if (block.MilepostMarkers != null)
            {
                foreach (var milepost in block.MilepostMarkers)
                {
                    mileposts.Add(new
                    {
                        text = milepost.Text,
                        offset = milepost.Offset,
                        lat = milepost.GeoPoint.Latitude,
                        lon = milepost.GeoPoint.Longitude
                    });
                }
            }

            // Milepost Measures
            if (block.MilepostMeasures != null)
            {
                foreach (var measure in block.MilepostMeasures)
                {
                    milepostMeasurements.Add(new
                    {
                        subdivisionId = trackFile.Id,
                        blockId = block.BlockId,
                        offset = measure.Offset,
                        measure = measure.Measure,
                        lat = measure.GeoPoint.Latitude,
                        lon = measure.GeoPoint.Longitude
                    });
                }
            }
        }

        // Switches are stored at trackFile level
        foreach (var sw in trackFile.Switches)
        {
            switches.Add(new
            {
                id = sw.SwitchId,
                name = sw.SwitchName,
                lat = sw.GeoPoint.Latitude,
                lon = sw.GeoPoint.Longitude
            });
        }

        trackFiles.Add(new
        {
            scac = trackFile.Subdivision.RailroadScac,
            subdivisionId = trackFile.Id,
            subdivisionName = trackFile.Subdivision.SubdivisionName,

            tracks = tracks,
            signals = signals,
            switches = switches,
            crossings = crossings,
            signages = signages,
            mileposts = mileposts,
            milepostMeasures = milepostMeasurements
        });
        }

            var output = new
            {
                trackFiles
            };

            File.WriteAllText(
                outputPath,
                JsonSerializer.Serialize(
                    output,
                    new JsonSerializerOptions
                    {
                        WriteIndented = true
                    }
                )
            );
    }
    }
}