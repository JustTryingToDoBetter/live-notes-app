<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Factories\HasFactory;

class Note extends Model
{
    use HasFactory; // Include the HasFactory trait for factory support
    // Define the fillable attributes for mass assignment
    protected $fillable = [
        'title',
        'content',
    ];


}
