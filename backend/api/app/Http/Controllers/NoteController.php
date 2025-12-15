<?php

namespace App\Http\Controllers;

use Illuminate\Http\Request;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Redis;// Uncomment when Redis is available
use App\Models\Note;


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
       // Using generic command method to ensure compatibility
       Redis::command('XADD', [
           'notes_stream',
           '*',
           'event', 'notes.created',
           'data', json_encode([
               'id' => $note->id,
               'title' => $note->title,
               'content' => $note->content,
               'created_at' => $note->created_at,
           ])
       ]);

       return response()->json($note, 201);
    }

}
