<?php

namespace App\Http\Controllers;

use Illuminate\Http\Request;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Redis;// Uncomment when Redis is available
use App\Models\Note;
use Illuminate\Support\Str;


class NoteController extends Controller
{
    // Retrieve all notes
    public function index()
    {
        return Cache::remember(
            'notes.all',
            30,
            fn() => Note::latest()->get()
        );
    }
    // Store a newly created note
    public function store(Request $request){
        // Validate incoming request
       $validated = $request->validate([
           'title' => 'required|string|max:255',
           'content' => 'required|string',
       ]);
       // Create and return the new note 
       // Persist the note to the database
       $note = Note::create($validated);
       // Invalidate the cache for all notes
       // Laravel's Cache facade is used to manage caching
       
       // Production-grade: Add to Redis Stream instead of Pub/Sub
       // XADD notes_stream * event notes.created data {...}
       // Use the underlying phpredis client for reliable XADD.
       $traceId = (string) Str::uuid();
       $payload = [
           'note_id' => (string) $note->id,
           'title' => $note->title,
           'content' => $note->content,
           'created_at' => now()->toIso8601String(),
       ];

       $fields = [
           'event' => 'notes.created',
           'note_id' => (string) $note->id,
           'trace_id' => $traceId,
           'retry_count' => '0',
           'payload' => json_encode($payload),
       ];

       $connection = Redis::connection();
       $client = $connection->client();

       if (method_exists($client, 'xAdd')) {
           // phpredis extension
           $client->xAdd('notes_stream', '*', $fields);
       } else {
           // Fallback: raw XADD with flat args
           $args = ['notes_stream', '*'];
           foreach ($fields as $k => $v) {
               $args[] = $k;
               $args[] = (string) $v;
           }
           $connection->command('XADD', $args);
       }

       return response()->json($note, 201);
    }

}
