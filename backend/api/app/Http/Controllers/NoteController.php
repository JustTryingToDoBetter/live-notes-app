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
       // Using standard xadd with explicit string casting
       $traceId= (string) Str::uuid(); // Example trace ID generation
       Redis::xadd('notes_stream', '*', [
           'event' => 'notes.created',
           'data' => (string) json_encode([
               'id' => $note->id,
               'title' => $note->title,
               'content' => $note->content,
               'created_at' => now()->toIso8601String(),
               'trace_id' => $traceId,
               'retry_count' => 0
           ])
       ]);

       return response()->json($note, 201);
    }

}
